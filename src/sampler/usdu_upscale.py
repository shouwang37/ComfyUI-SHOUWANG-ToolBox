# ═══ 守望-终极SD放大🐢（UltimateSDUpscale 移植节点）═══
# 功能：将图像放大后按分块进行 img2img 重绘并修复接缝（大图分块放大，降低显存需求）。
# 输入/输出开头为 PIPE_LINE 节点束（模型/条件/VAE 可从束中获取，也可单独连接），
# 实现参考 src/sampler/Partial_repainting.py。
# 本文件为单文件版：由 usdu_utils / usdu_processing / usdu_algorithm / usdu_upscale 四个模块合并而成，
# 分节结构见下方 ═══ ①~④ ═══ 注释（每节内实现与原模块保持一致）。
import math
import logging
from contextlib import contextmanager
from enum import Enum

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageFilter, ImageDraw, ImageOps
from tqdm import tqdm

import comfy.samplers
import comfy.sample
import comfy.model_management
import comfy.utils as comfy_utils
import latent_preview
from nodes import common_ksampler, VAEEncode, VAEDecode, VAEDecodeTiled
from comfy_extras.nodes_custom_sampler import SamplerCustom
from comfy_extras.nodes_upscale_model import ImageUpscaleWithModel

if not hasattr(Image, 'Resampling'):  # 兼容旧版 Pillow
    Image.Resampling = Image

BLUR_KERNEL_SIZE = 15

logger = logging.getLogger(__name__)


# ═══ ① 工具函数与共享状态（原 usdu_utils.py）═══
# 包含：张量/PIL 互转、裁剪区域计算、条件裁剪（ControlNet/GLIGEN/area/mask/参考潜变量）、
# 全局共享状态、模型放大器封装。
def tensor_to_pil(img_tensor, batch_index=0):
    # 批量张量 [batch, height, width, channels] → RGB PIL 图像（假设通道=3）
    safe_tensor = torch.nan_to_num(img_tensor[batch_index])
    return Image.fromarray((255 * safe_tensor.cpu().numpy()).astype(np.uint8))


def pil_to_tensor(image):
    # PIL 图像 → 张量 [1, height, width, channels]
    image = np.array(image).astype(np.float32) / 255.0
    image = torch.from_numpy(image).unsqueeze(0)
    if len(image.shape) == 3:  # 灰度图补通道维
        image = image.unsqueeze(-1)
    return image


def controlnet_hint_to_pil(tensor, batch_index=0):
    return tensor_to_pil(tensor.movedim(1, -1), batch_index)


def pil_to_controlnet_hint(img):
    return pil_to_tensor(img).movedim(-1, 1)


def crop_tensor(tensor, region):
    # 张量 [batch, height, width, channels] 按区域裁剪
    x1, y1, x2, y2 = region
    return tensor[:, y1:y2, x1:x2, :]


def resize_tensor(tensor, size, mode="nearest-exact"):
    # 张量 [B, C, H, W] 缩放到 [B, C, size[0], size[1]]
    return torch.nn.functional.interpolate(tensor, size=size, mode=mode)


def get_crop_region(mask, pad=0):
    # 黑白 L 模式 PIL 图像 → 白色矩形区域坐标（等价 A1111 modules/masking.py 的 get_crop_region）
    coordinates = mask.getbbox()
    if coordinates is not None:
        x1, y1, x2, y2 = coordinates
    else:
        x1, y1, x2, y2 = mask.width, mask.height, 0, 0
    # 应用填充
    x1 = max(x1 - pad, 0)
    y1 = max(y1 - pad, 0)
    x2 = min(x2 + pad, mask.width)
    y2 = min(y2 + pad, mask.height)
    return fix_crop_region((x1, y1, x2, y2), (mask.width, mask.height))


def fix_crop_region(region, image_size):
    # 移除 get_crop_region 多出的一个像素
    image_width, image_height = image_size
    x1, y1, x2, y2 = region
    if x2 < image_width:
        x2 -= 1
    if y2 < image_height:
        y2 -= 1
    return x1, y1, x2, y2


def expand_crop(region, width, height, target_width, target_height):
    '''
    将裁剪区域扩展到指定目标尺寸。
    :param region: (x1, y1, x2, y2) 左上/右下坐标，要求 x2 > x1 且 y2 > y1
    :param width: 原图宽度
    :param height: 原图高度
    :param target_width: 目标宽度
    :param target_height: 目标高度
    '''
    x1, y1, x2, y2 = region
    actual_width = x2 - x1
    actual_height = y2 - y1

    # 先向右扩展一半差值
    width_diff = target_width - actual_width
    x2 = min(x2 + width_diff // 2, width)
    # 再向左扩展剩余差值（含右侧无法扩展的部分）
    width_diff = target_width - (x2 - x1)
    x1 = max(x1 - width_diff, 0)
    # 尝试再次向右扩展
    width_diff = target_width - (x2 - x1)
    x2 = min(x2 + width_diff, width)

    # 先向下扩展一半差值
    height_diff = target_height - actual_height
    y2 = min(y2 + height_diff // 2, height)
    # 再向上扩展剩余差值（含下方无法扩展的部分）
    height_diff = target_height - (y2 - y1)
    y1 = max(y1 - height_diff, 0)
    # 尝试再次向下扩展
    height_diff = target_height - (y2 - y1)
    y2 = min(y2 + height_diff, height)

    return (x1, y1, x2, y2), (target_width, target_height)


def resize_region(region, init_size, resize_size):
    # 将裁剪区域按比例映射到另一个尺寸的图像上
    x1, y1, x2, y2 = region
    init_width, init_height = init_size
    resize_width, resize_height = resize_size
    x1 = math.floor(x1 * resize_width / init_width)
    x2 = math.ceil(x2 * resize_width / init_width)
    y1 = math.floor(y1 * resize_height / init_height)
    y2 = math.ceil(y2 * resize_height / init_height)
    return (x1, y1, x2, y2)


def pad_image(image, left_pad, right_pad, top_pad, bottom_pad, fill=False, blur=False):
    '''
    按给定像素数填充图像边缘，用边缘像素数据填充空白。
    :param image: PIL 图像
    :param left_pad/right_pad/top_pad/bottom_pad: 各方向填充像素数
    :param fill: 是否用边缘数据填充
    :param blur: 是否模糊填充边缘
    :return: 尺寸为 (w+left+right, h+top+bottom) 的 PIL 图像
    '''
    left_edge = image.crop((0, 1, 1, image.height - 1))
    right_edge = image.crop((image.width - 1, 1, image.width, image.height - 1))
    top_edge = image.crop((1, 0, image.width - 1, 1))
    bottom_edge = image.crop((1, image.height - 1, image.width - 1, image.height))
    new_width = image.width + left_pad + right_pad
    new_height = image.height + top_pad + bottom_pad
    padded_image = Image.new(image.mode, (new_width, new_height))
    padded_image.paste(image, (left_pad, top_pad))
    if fill:
        for i in range(left_pad):
            edge = left_edge.resize(
                (1, new_height - i * (top_pad + bottom_pad) // left_pad), resample=Image.Resampling.NEAREST)
            padded_image.paste(edge, (i, i * top_pad // left_pad))
        for i in range(right_pad):
            edge = right_edge.resize(
                (1, new_height - i * (top_pad + bottom_pad) // right_pad), resample=Image.Resampling.NEAREST)
            padded_image.paste(edge, (new_width - 1 - i, i * top_pad // right_pad))
        for i in range(top_pad):
            edge = top_edge.resize(
                (new_width - i * (left_pad + right_pad) // top_pad, 1), resample=Image.Resampling.NEAREST)
            padded_image.paste(edge, (i * left_pad // top_pad, i))
        for i in range(bottom_pad):
            edge = bottom_edge.resize(
                (new_width - i * (left_pad + right_pad) // bottom_pad, 1), resample=Image.Resampling.NEAREST)
            padded_image.paste(edge, (i * left_pad // bottom_pad, new_height - 1 - i))
        if blur and not (left_pad == right_pad == top_pad == bottom_pad == 0):
            padded_image = padded_image.filter(ImageFilter.GaussianBlur(BLUR_KERNEL_SIZE))
            padded_image.paste(image, (left_pad, top_pad))
    return padded_image


def pad_image2(image, left_pad, right_pad, top_pad, bottom_pad, fill=False, blur=False):
    '''
    按给定像素数填充图像边缘，仅直线复制边缘数据（比 pad_image 快）。
    :param image: PIL 图像
    :param left_pad/right_pad/top_pad/bottom_pad: 各方向填充像素数
    :param fill: 是否用边缘数据填充
    :param blur: 是否模糊填充边缘
    :return: 尺寸为 (w+left+right, h+top+bottom) 的 PIL 图像
    '''
    left_edge = image.crop((0, 1, 1, image.height - 1))
    right_edge = image.crop((image.width - 1, 1, image.width, image.height - 1))
    top_edge = image.crop((1, 0, image.width - 1, 1))
    bottom_edge = image.crop((1, image.height - 1, image.width - 1, image.height))
    new_width = image.width + left_pad + right_pad
    new_height = image.height + top_pad + bottom_pad
    padded_image = Image.new(image.mode, (new_width, new_height))
    padded_image.paste(image, (left_pad, top_pad))
    if fill:
        if left_pad > 0:
            padded_image.paste(left_edge.resize((left_pad, new_height), resample=Image.Resampling.NEAREST), (0, 0))
        if right_pad > 0:
            padded_image.paste(right_edge.resize((right_pad, new_height),
                               resample=Image.Resampling.NEAREST), (new_width - right_pad, 0))
        if top_pad > 0:
            padded_image.paste(top_edge.resize((new_width, top_pad), resample=Image.Resampling.NEAREST), (0, 0))
        if bottom_pad > 0:
            padded_image.paste(bottom_edge.resize((new_width, bottom_pad),
                               resample=Image.Resampling.NEAREST), (0, new_height - bottom_pad))
        if blur and not (left_pad == right_pad == top_pad == bottom_pad == 0):
            padded_image = padded_image.filter(ImageFilter.GaussianBlur(BLUR_KERNEL_SIZE))
            padded_image.paste(image, (left_pad, top_pad))
    return padded_image


def pad_tensor(tensor, left_pad, right_pad, top_pad, bottom_pad, fill=False, blur=False):
    '''
    按给定像素数填充图像张量边缘，复制边缘数据填充。
    :param tensor: [B, H, W, C] 张量
    :param left_pad/right_pad/top_pad/bottom_pad: 各方向填充像素数
    :return: [B, H+top+bottom, W+left+right, C] 张量
    '''
    batch_size, channels, height, width = tensor.shape
    h_pad = left_pad + right_pad
    v_pad = top_pad + bottom_pad
    new_width = width + h_pad
    new_height = height + v_pad

    # 创建空图像
    padded = torch.zeros((batch_size, channels, new_height, new_width), dtype=tensor.dtype)

    # 将原图复制到填充张量中心
    padded[:, :, top_pad:top_pad + height, left_pad:left_pad + width] = tensor

    # 复制原图边缘到填充区域
    if top_pad > 0:
        padded[:, :, :top_pad, :] = padded[:, :, top_pad:top_pad + 1, :]  # 上边缘
    if bottom_pad > 0:
        padded[:, :, -bottom_pad:, :] = padded[:, :, -bottom_pad - 1:-bottom_pad, :]  # 下边缘
    if left_pad > 0:
        padded[:, :, :, :left_pad] = padded[:, :, :, left_pad:left_pad + 1]  # 左边缘
    if right_pad > 0:
        padded[:, :, :, -right_pad:] = padded[:, :, :, -right_pad - 1:-right_pad]  # 右边缘

    return padded


def resize_and_pad_image(image, width, height, fill=False, blur=False):
    '''
    将图像等比缩放到目标宽高并填充到目标尺寸。
    :param image: PIL 图像
    :param width: 目标宽度
    :param height: 目标高度
    :param fill: 是否用边缘数据填充
    :param blur: 是否模糊填充边缘
    :return: (尺寸 (width, height) 的 PIL 图像, (水平填充, 垂直填充))
    '''
    width_ratio = width / image.width
    height_ratio = height / image.height
    if height_ratio > width_ratio:
        resize_ratio = width_ratio
    else:
        resize_ratio = height_ratio
    resize_width = round(image.width * resize_ratio)
    resize_height = round(image.height * resize_ratio)
    resized = image.resize((resize_width, resize_height), resample=Image.Resampling.LANCZOS)
    # 填充未覆盖的侧边
    horizontal_pad = (width - resize_width) // 2
    vertical_pad = (height - resize_height) // 2
    result = pad_image2(resized, horizontal_pad, horizontal_pad, vertical_pad, vertical_pad, fill, blur)
    result = result.resize((width, height), resample=Image.Resampling.LANCZOS)
    return result, (horizontal_pad, vertical_pad)


def resize_and_pad_tensor(tensor, width, height, fill=False, blur=False):
    '''
    将图像张量等比缩放到目标宽高并填充到目标尺寸。
    :param tensor: [B, H, W, C] 张量
    :param width: 目标宽度
    :param height: 目标高度
    :return: [B, height, width, C] 张量
    '''
    # 等比缩放到最接近目标尺寸的尺寸
    width_ratio = width / tensor.shape[3]
    height_ratio = height / tensor.shape[2]
    if height_ratio > width_ratio:
        resize_ratio = width_ratio
    else:
        resize_ratio = height_ratio
    resize_width = round(tensor.shape[3] * resize_ratio)
    resize_height = round(tensor.shape[2] * resize_ratio)
    resized = F.interpolate(tensor, size=(resize_height, resize_width), mode='nearest-exact')
    # 填充未覆盖的侧边
    horizontal_pad = (width - resize_width) // 2
    vertical_pad = (height - resize_height) // 2
    result = pad_tensor(resized, horizontal_pad, horizontal_pad, vertical_pad, vertical_pad, fill, blur)
    result = F.interpolate(result, size=(height, width), mode='nearest-exact')
    return result


def crop_controlnet(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad):
    """
    将 ControlNet 提示按区域裁剪并缩放到分块尺寸。
    支持多区域：提示按区域裁剪缩放后在批次维拼接。

    :param cond_dict: 包含条件的字典
    :param regions: (x1, y1, x2, y2) 或坐标元组列表
    :param init_size: 生成 ControlNet 提示的原始图像尺寸
    :param canvas_size: 提示将被缩放到的图像尺寸
    :param tile_size: 每个裁剪提示将缩放到的尺寸
    :param w_pad: 添加到每个裁剪提示的水平填充
    :param h_pad: 添加到每个裁剪提示的垂直填充
    """
    if "control" not in cond_dict:
        return
    if not isinstance(regions, list):
        regions = [regions]
    c = cond_dict["control"]
    controlnet = c.copy()
    cond_dict["control"] = controlnet
    while c is not None:
        # hint 形状 (B, C, H, W)
        hint = controlnet.cond_hint_original
        tiled_hints = []
        for region in regions:
            resized_crop = resize_region(region, canvas_size, hint.shape[:-3:-1])
            tiled_hint = crop_tensor(hint.movedim(1, -1), resized_crop).movedim(-1, 1)
            tiled_hint = resize_tensor(tiled_hint, tile_size[::-1])
            tiled_hints.append(tiled_hint)
        controlnet.cond_hint_original = torch.cat(tiled_hints, dim=0)
        c = c.previous_controlnet
        controlnet.set_previous_controlnet(c.copy() if c is not None else None)
        controlnet = controlnet.previous_controlnet


def region_intersection(region1, region2):
    """
    返回两个矩形区域的交集坐标。
    :param region1: (x1, y1, x2, y2) 矩形区域
    :param region2: 同格式的第二个矩形区域
    :return: (x1, y1, x2, y2) 交集区域；无交集时返回 None
    """
    x1, y1, x2, y2 = region1
    x1_, y1_, x2_, y2_ = region2
    x1 = max(x1, x1_)
    y1 = max(y1, y1_)
    x2 = min(x2, x2_)
    y2 = min(y2, y2_)
    if x1 >= x2 or y1 >= y2:
        return None
    return (x1, y1, x2, y2)


def crop_gligen(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad):
    """
    将 GLIGEN 位置条件裁剪到指定区域。

    不支持多区域。
    """
    if "gligen" not in cond_dict:
        return

    # 多区域时仅使用第一个区域
    region = regions if isinstance(regions, tuple) else regions[0]

    type, model, cond = cond_dict["gligen"]
    if type != "position":
        from warnings import warn
        warn(f"Unknown gligen type {type}")
        return
    cropped = []
    for c in cond:
        emb, h, w, y, x = c
        # 获取放大图像中盒子的坐标
        x1 = x * 8
        y1 = y * 8
        x2 = x1 + w * 8
        y2 = y1 + h * 8
        gligen_upscaled_box = resize_region((x1, y1, x2, y2), init_size, canvas_size)

        # 计算 GLIGEN 盒子与区域的交集
        intersection = region_intersection(gligen_upscaled_box, region)
        if intersection is None:
            continue
        x1, y1, x2, y2 = intersection

        # 偏移 GLIGEN 盒子使原点位于分块区域左上角
        x1 -= region[0]
        y1 -= region[1]
        x2 -= region[0]
        y2 -= region[1]

        # 添加填充
        x1 += w_pad
        y1 += h_pad
        x2 += w_pad
        y2 += h_pad

        # 设置新的位置参数
        h = (y2 - y1) // 8
        w = (x2 - x1) // 8
        x = x1 // 8
        y = y1 // 8
        cropped.append((emb, h, w, y, x))

    cond_dict["gligen"] = (type, model, cropped)


def crop_area(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad):
    """
    将区域条件裁剪到指定区域。

    不支持多区域。
    """
    if "area" not in cond_dict:
        return

    # 多区域时仅使用第一个区域
    region = regions if isinstance(regions, tuple) else regions[0]

    # 将区域条件缩放到画布尺寸并限制在分块区域内
    h, w, y, x = cond_dict["area"]
    w, h, x, y = 8 * w, 8 * h, 8 * x, 8 * y
    x1, y1, x2, y2 = resize_region((x, y, x + w, y + h), init_size, canvas_size)
    intersection = region_intersection((x1, y1, x2, y2), region)
    if intersection is None:
        del cond_dict["area"]
        del cond_dict["strength"]
        return
    x1, y1, x2, y2 = intersection

    # 偏移原点到分块左上角
    x1 -= region[0]
    y1 -= region[1]
    x2 -= region[0]
    y2 -= region[1]

    # 添加填充
    x1 += w_pad
    y1 += h_pad
    x2 += w_pad
    y2 += h_pad

    # 设置分块参数
    w, h = (x2 - x1) // 8, (y2 - y1) // 8
    x, y = x1 // 8, y1 // 8

    cond_dict["area"] = (h, w, y, x)


def crop_mask(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad):
    """
    将遮罩条件裁剪到指定区域。

    不支持多区域。
    """
    if "mask" not in cond_dict:
        return

    # 多区域时仅使用第一个区域
    region = regions if isinstance(regions, tuple) else regions[0]

    mask_tensor = cond_dict["mask"]  # (B, H, W)
    masks = []
    for i in range(mask_tensor.shape[0]):
        # 转换为 PIL 图像
        mask = tensor_to_pil(mask_tensor, i)  # W x H

        # 将遮罩缩放到画布尺寸
        mask = mask.resize(canvas_size, Image.Resampling.BICUBIC)

        # 裁剪遮罩到区域
        mask = mask.crop(region)

        # 添加填充
        mask, _ = resize_and_pad_image(mask, tile_size[0], tile_size[1], fill=True)

        # 缩放到分块尺寸
        if tile_size != mask.size:
            mask = mask.resize(tile_size, Image.Resampling.BICUBIC)

        # 转换回张量
        mask = pil_to_tensor(mask)  # (1, H, W, 1)
        mask = mask.squeeze(-1)  # (1, H, W)
        masks.append(mask)

    cond_dict["mask"] = torch.cat(masks, dim=0)  # (B, H, W)


def crop_reference_latents(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad):
    """
    裁剪参考潜变量（Flux-Kontext 支持）。

    1. 将每个潜变量缩放到 canvas_size（潜空间单位）
    2. 裁剪区域 region（像素坐标）
    3. 将裁剪结果降采样到分块尺寸（潜空间单位）

    不支持多区域。
    """
    latents = cond_dict.get("reference_latents")
    if not isinstance(latents, list):
        return  # 无需处理

    # 多区域时仅使用第一个区域
    region = regions if isinstance(regions, tuple) else regions[0]

    k = 8  # 像素空间 → 潜空间降采样因子（SD 类模型）

    W_can_px, H_can_px = canvas_size
    # 画布尺寸的潜空间单位
    W_can_lat, H_can_lat = W_can_px // k, H_can_px // k

    W_tile_px, H_tile_px = tile_size
    W_tile_lat, H_tile_lat = max(1, W_tile_px // k), max(1, H_tile_px // k)

    x1_px, y1_px, x2_px, y2_px = region

    new_latents = []
    for t in latents:  # (B,C,H_lat_in,W_lat_in)
        has_5d = False
        if t.ndim == 5:  # (B,C,1,H_lat_in,W_lat_in)
            has_5d = True
            t = t.squeeze(2)
        if t.ndim != 4:
            raise ValueError(f"expected BCHW, got {t.shape}")

        # 1. 仅在需要时缩放到画布分辨率（潜空间单位）
        if t.shape[-2:] != (H_can_lat, W_can_lat):
            t = F.interpolate(t,
                              size=(H_can_lat, W_can_lat),
                              mode="bilinear",
                              align_corners=False)

        # 2. 将像素裁剪转换为潜空间切片
        w0_lat = int(round(x1_px / k))
        w1_lat = int(round(x2_px / k))
        h0_lat = int(round(y1_px / k))
        h1_lat = int(round(y2_px / k))

        cropped = t[:, :, h0_lat:h1_lat, w0_lat:w1_lat]  # 视图

        # 3. 降采样到潜空间分块尺寸
        cropped = F.interpolate(cropped,
                                size=(H_tile_lat, W_tile_lat),
                                mode="bilinear",
                                align_corners=False)
        if has_5d:
            cropped = cropped.unsqueeze(2)
        new_latents.append(cropped)

    cond_dict["reference_latents"] = new_latents


def crop_cond(cond, regions, init_size, canvas_size, tile_size, w_pad=0, h_pad=0):
    cropped = []
    for emb, x in cond:
        cond_dict = x.copy()
        n = [emb, cond_dict]
        crop_controlnet(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad)
        crop_gligen(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad)
        crop_area(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad)
        crop_mask(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad)
        crop_reference_latents(cond_dict, regions, init_size, canvas_size, tile_size, w_pad, h_pad)
        cropped.append(n)
    return cropped


def flatten(img, bgcolor):
    # 用背景色替换透明通道
    if img.mode in ("RGB"):
        return img
    return Image.alpha_composite(Image.new("RGBA", img.size, bgcolor), img).convert("RGB")


# 全局共享状态（替代 A1111 的 modules/shared）
class Options:
    img2img_background_color = "#ffffff"  # 背景色暂设为白色


class State:
    interrupted = False

    def begin(self):
        pass

    def end(self):
        pass


opts = Options()
state = State()

# 只保存一个放大器
sd_upscalers = [None]
# ComfyUI 节点可用的放大器
actual_upscaler = None

# 待放大的图像批次
batch = []
batch_as_tensor = None


def torch_gc():
    pass


# ═══ 放大器封装（替代 A1111 的 modules/upscaler）═══
class Upscaler:

    def upscale(self, img: Image, scale, selected_model: str = None):
        global batch
        if scale == 1.0:
            return img
        if (actual_upscaler is None):
            return img.resize((img.width * scale, img.height * scale), Image.Resampling.LANCZOS)
        if "execute" in dir(ImageUpscaleWithModel):
            # V3 schema: https://github.com/comfyanonymous/ComfyUI/pull/10149
            (upscaled,) = ImageUpscaleWithModel.execute(actual_upscaler, batch_as_tensor)
        else:
            (upscaled,) = ImageUpscaleWithModel().upscale(actual_upscaler, batch_as_tensor)
        batch = [tensor_to_pil(upscaled, i) for i in range(len(upscaled))]
        return batch[0]


class UpscalerData:
    name = ""
    data_path = ""

    def __init__(self):
        self.scaler = Upscaler()


# ═══ ② 处理管线（原 usdu_processing.py）═══
# 包含：StableDiffusionProcessing 处理对象、单块/批量分块采样合成（process_images / process_batch_tiles）、
# ControlNet 补丁裁剪（crop_model_cond / ModelPatchCropper）。

# 取自 USDU 脚本的分块模式枚举
class USDUMode(Enum):
    LINEAR = 0
    CHESS = 1
    NONE = 2

class USDUSFMode(Enum):
    NONE = 0
    BAND_PASS = 1
    HALF_TILE = 2
    HALF_TILE_PLUS_INTERSECTIONS = 3

class StableDiffusionProcessing:

    def __init__(
        self,
        init_img,
        model,
        positive,
        negative,
        vae,
        seed,
        steps,
        cfg,
        sampler_name,
        scheduler,
        denoise,
        upscale_by,
        uniform_tile_mode,
        tiled_decode,
        tile_width,
        tile_height,
        redraw_mode,
        seam_fix_mode,
        custom_sampler=None,
        custom_sigmas=None,
        batch_size=1,
        guider=None,
    ):
        # USDU 脚本使用的变量
        self.init_images = [init_img]
        self.image_mask = Image.new('L', init_img.size, 0)  # 占位遮罩
        self.mask_blur = 0
        self.inpaint_full_res_padding = 0
        self.width = init_img.width * upscale_by
        self.height = init_img.height * upscale_by
        self.rows = round(self.height / tile_height)
        self.cols = round(self.width / tile_width)

        # 基于 guider 的采样（guider 封装模型 + 条件 + cfg）
        self.guider = guider

        # ComfyUI 采样器输入
        self.model = guider.model_patcher if guider is not None else model
        self.positive = positive
        self.negative = negative
        self.vae = vae
        self.seed = seed
        self.steps = steps
        self.cfg = cfg
        self.sampler_name = sampler_name
        self.scheduler = scheduler
        self.denoise = denoise

        # 可选自定义采样器与 sigmas
        self.custom_sampler = custom_sampler
        self.custom_sigmas = custom_sigmas

        if guider is None and (custom_sampler is not None) ^ (custom_sigmas is not None):
            logger.warning("Both custom sampler and custom sigmas must be provided, defaulting to widget sampler and sigmas")

        # 本脚本专用变量
        self.init_size = init_img.width, init_img.height
        self.upscale_by = upscale_by
        self.uniform_tile_mode = uniform_tile_mode
        self.tiled_decode = tiled_decode
        self.batch_size = batch_size
        self.vae_decoder = VAEDecode()
        self.vae_encoder = VAEEncode()
        self.vae_decoder_tiled = VAEDecodeTiled()

        if self.tiled_decode:
            logger.info("Using tiled decode")

        # USDU 脚本需要的其他 A1111 变量（本脚本中未使用）
        self.extra_generation_params = {}

        # 整个流程的进度条（而非每个分块单独进度条）
        self.progress_bar_enabled = False
        if comfy_utils.PROGRESS_BAR_ENABLED:
            self.progress_bar_enabled = True
            comfy_utils.PROGRESS_BAR_ENABLED = True
            self.tiles = 0
            if redraw_mode.value != USDUMode.NONE.value:
                self.tiles += self.rows * self.cols
            if seam_fix_mode.value == USDUSFMode.BAND_PASS.value:
                self.tiles += (self.rows - 1) + (self.cols - 1)
            elif seam_fix_mode.value == USDUSFMode.HALF_TILE.value:
                self.tiles += (self.rows - 1) * self.cols + (self.cols - 1) * self.rows
            elif seam_fix_mode.value == USDUSFMode.HALF_TILE_PLUS_INTERSECTIONS.value:
                self.tiles += (self.rows - 1) * self.cols + (self.cols - 1) * self.rows + (self.rows - 1) * (self.cols - 1)
            self.pbar: tqdm = None
            # self.pbar = tqdm(total=self.tiles, desc='USDU') # 在此创建进度条会导致空进度条显示

    def __del__(self):
        # 节点完成或取消时恢复进度条标志
        if self.progress_bar_enabled:
            comfy_utils.PROGRESS_BAR_ENABLED = True

class Processed:

    def __init__(self, p: StableDiffusionProcessing, images: list, seed: int, info: str):
        self.images = images
        self.seed = seed
        self.info = info

    def infotext(self, p: StableDiffusionProcessing, index):
        return None


def fix_seed(p: StableDiffusionProcessing):
    pass


def sample(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent, denoise, custom_sampler, custom_sigmas):
    """根据输入选择采样方式"""
    # 自定义采样器与 sigmas
    if custom_sampler is not None and custom_sigmas is not None:
        kwargs = dict(
            model=model,
            add_noise=True,
            noise_seed=seed,
            cfg=cfg,
            positive=positive,
            negative=negative,
            sampler=custom_sampler,
            sigmas=custom_sigmas,
            latent_image=latent
        )
        if "execute" in dir(SamplerCustom):
            (samples, _) = SamplerCustom.execute(**kwargs)
        else:
            custom_sample = SamplerCustom()
            (samples, _) = getattr(custom_sample, custom_sample.FUNCTION)(**kwargs)
        return samples

    # 默认
    (samples,) = common_ksampler(model, seed, steps, cfg, sampler_name,
                                 scheduler, positive, negative, latent, denoise=denoise)
    return samples


def sample_with_guider(guider, sampler, sigmas, seed, latent):
    """使用 guider（封装模型、条件与 cfg）采样"""
    latent_image = latent["samples"]
    latent_image = comfy.sample.fix_empty_latent_channels(guider.model_patcher, latent_image)

    noise = comfy.sample.prepare_noise(latent_image, seed)

    callback = latent_preview.prepare_callback(guider.model_patcher, sigmas.shape[-1] - 1)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED

    samples = guider.sample(noise, latent_image, sampler, sigmas,
                            denoise_mask=latent.get("noise_mask", None),
                            callback=callback, disable_pbar=disable_pbar, seed=seed)
    samples = samples.to(comfy.model_management.intermediate_device())
    return {"samples": samples}


def process_images(p: StableDiffusionProcessing) -> Processed:
    # A1111 中主图像生成发生的位置

    # 显示进度条
    if p.progress_bar_enabled and p.pbar is None:
        p.pbar = tqdm(total=p.tiles, desc='USDU', unit='tile')

    # 设置
    image_mask = p.image_mask.convert('L')
    init_image = p.init_images[0]

    # 定位遮罩白色区域并添加填充
    crop_region = get_crop_region(image_mask, p.inpaint_full_res_padding)

    if p.uniform_tile_mode:
        # 扩展裁剪区域以匹配处理尺寸比例，然后缩放到处理尺寸
        x1, y1, x2, y2 = crop_region
        crop_width = x2 - x1
        crop_height = y2 - y1
        crop_ratio = crop_width / crop_height
        p_ratio = p.width / p.height
        if crop_ratio > p_ratio:
            target_width = crop_width
            target_height = round(crop_width / p_ratio)
        else:
            target_width = round(crop_height * p_ratio)
            target_height = crop_height
        crop_region, _ = expand_crop(crop_region, image_mask.width, image_mask.height, target_width, target_height)
        tile_size = p.width, p.height
    else:
        # 使用可容纳遮罩的最小尺寸，最小化分块尺寸但可能导致模型未训练的尺寸
        x1, y1, x2, y2 = crop_region
        crop_width = x2 - x1
        crop_height = y2 - y1
        target_width = math.ceil(crop_width / 8) * 8
        target_height = math.ceil(crop_height / 8) * 8
        crop_region, tile_size = expand_crop(crop_region, image_mask.width,
                                             image_mask.height, target_width, target_height)

    # 模糊遮罩
    if p.mask_blur > 0:
        image_mask = image_mask.filter(ImageFilter.GaussianBlur(p.mask_blur))

    # 裁剪图像以获取生成用分块
    tiles = [img.crop(crop_region) for img in batch]

    # 假设批次中所有图像尺寸相同
    initial_tile_size = tiles[0].size

    # 必要时缩放
    for i, tile in enumerate(tiles):
        if tile.size != tile_size:
            tiles[i] = tile.resize(tile_size, Image.Resampling.LANCZOS)

    # 编码图像
    batched_tiles = torch.cat([pil_to_tensor(tile) for tile in tiles], dim=0)
    (latent,) = p.vae_encoder.encode(p.vae, batched_tiles)

    if p.guider is not None:
        # 基于 guider 的采样
        with crop_model_cond(p.model, crop_region, p.init_size, init_image.size, tile_size) as model:
            samples = sample_with_guider(p.guider, p.custom_sampler, p.custom_sigmas, p.seed, latent)
    else:
        # 裁剪条件
        positive_cropped = crop_cond(p.positive, crop_region, p.init_size, init_image.size, tile_size)
        negative_cropped = crop_cond(p.negative, crop_region, p.init_size, init_image.size, tile_size)

        with crop_model_cond(p.model, crop_region, p.init_size, init_image.size, tile_size) as model:
            # 生成样本
            samples = sample(model, p.seed, p.steps, p.cfg, p.sampler_name, p.scheduler, positive_cropped,
                            negative_cropped, latent, p.denoise, p.custom_sampler, p.custom_sigmas)

    # 更新进度条
    if p.progress_bar_enabled:
        assert p.pbar is not None
        p.pbar.update(1)

    # 解码样本
    if not p.tiled_decode:
        (decoded,) = p.vae_decoder.decode(p.vae, samples)
    else:
        (decoded,) = p.vae_decoder_tiled.decode(p.vae, samples, 512)  # 默认分块尺寸 512

    # 将样本转换为 PIL 图像
    tiles_sampled = [tensor_to_pil(decoded, i) for i in range(len(decoded))]

    for i, tile_sampled in enumerate(tiles_sampled):
        init_image = batch[i]

        # 缩放回原始尺寸
        if tile_sampled.size != initial_tile_size:
            tile_sampled = tile_sampled.resize(initial_tile_size, Image.Resampling.LANCZOS)

        # 将分块放入正确位置
        image_tile_only = Image.new('RGBA', init_image.size)
        image_tile_only.paste(tile_sampled, crop_region[:2])

        # 将遮罩作为 alpha 通道添加
        # 必须复制，因为边缘可能变黑
        temp = image_tile_only.copy()
        temp.putalpha(image_mask)
        image_tile_only.paste(temp, image_tile_only)

        # 根据 alpha 通道遮罩将分块添加回初始图像
        result = init_image.convert('RGBA')
        result.alpha_composite(image_tile_only)

        # 转换回 RGB
        result = result.convert('RGB')

        batch[i] = result

    processed = Processed(p, [batch[0]], p.seed, "")
    return processed


def process_batch_tiles(
    p: StableDiffusionProcessing,
    tiles_coords,
    images,
    calc_rectangle_fn,
):
    """编码、采样并解码一批分块，然后合成回 *images*。

    与 process_images()（处理单个预构建遮罩）不同，本函数通过 calc_rectangle_fn
    为每个分块构建遮罩，并在一次批量 编码 → 采样 → 解码 中处理每个 (分块, 图像) 组合。
    """
    if not tiles_coords or not images:
        return images

    if p.progress_bar_enabled and p.pbar is None:
        p.pbar = tqdm(total=getattr(p, "tiles", 0), desc='USDU', unit='tile')

    batch_tiles = []
    batch_masks = []
    batch_crop_regions = []
    batch_tile_sizes = []

    for image in images:
        for tx, ty in tiles_coords:
            tile_mask = Image.new("L", (image.width, image.height), "black")
            tile_draw = ImageDraw.Draw(tile_mask)
            tile_draw.rectangle(calc_rectangle_fn(tx, ty), fill="white")

            crop_region = get_crop_region(tile_mask, p.inpaint_full_res_padding)

            if p.uniform_tile_mode:
                x1, y1, x2, y2 = crop_region
                crop_w = x2 - x1
                crop_h = y2 - y1
                crop_ratio = crop_w / crop_h if crop_h != 0 else 1.0
                p_ratio = p.width / p.height if p.height != 0 else 1.0
                if crop_ratio > p_ratio:
                    target_w = crop_w
                    target_h = round(crop_w / p_ratio)
                else:
                    target_w = round(crop_h * p_ratio)
                    target_h = crop_h
                crop_region, _ = expand_crop(crop_region, tile_mask.width, tile_mask.height, target_w, target_h)
                tile_size = (p.width, p.height)
            else:
                x1, y1, x2, y2 = crop_region
                crop_w = x2 - x1
                crop_h = y2 - y1
                target_w = math.ceil(crop_w / 8) * 8
                target_h = math.ceil(crop_h / 8) * 8
                crop_region, tile_size = expand_crop(crop_region, tile_mask.width, tile_mask.height, target_w, target_h)

            if p.mask_blur > 0:
                tile_mask = tile_mask.filter(ImageFilter.GaussianBlur(p.mask_blur))

            cropped_tile = image.crop(crop_region)
            initial_tile_size = cropped_tile.size
            if cropped_tile.size != tile_size:
                cropped_tile = cropped_tile.resize(tile_size, Image.Resampling.LANCZOS)

            batch_tiles.append((cropped_tile, initial_tile_size))
            batch_masks.append(tile_mask)
            batch_crop_regions.append(crop_region)
            batch_tile_sizes.append(tile_size)

    # 将所有分块编码为单个潜变量批次
    batched_tensors = torch.cat([pil_to_tensor(tile) for tile, _ in batch_tiles], dim=0)
    (latent,) = p.vae_encoder.encode(p.vae, batched_tensors)

    first_tile_size = batch_tile_sizes[0]

    if p.guider is not None:
        # 基于 guider 的采样
        with crop_model_cond(p.model, batch_crop_regions, p.init_size, images[0].size, first_tile_size) as model:
            samples = sample_with_guider(p.guider, p.custom_sampler, p.custom_sigmas, p.seed, latent)
    else:
        # 使用完整区域列表裁剪条件（假设第一个分块尺寸统一）
        positive_cropped = crop_cond(p.positive, batch_crop_regions, p.init_size, images[0].size, first_tile_size)
        negative_cropped = crop_cond(p.negative, batch_crop_regions, p.init_size, images[0].size, first_tile_size)

        with crop_model_cond(p.model, batch_crop_regions, p.init_size, images[0].size, first_tile_size) as model:
            samples = sample(model, p.seed, p.steps, p.cfg, p.sampler_name, p.scheduler,
                             positive_cropped, negative_cropped, latent, p.denoise,
                             p.custom_sampler, p.custom_sigmas)

    # 每次批量调用更新一次进度条（每个分块坐标一步）
    if p.progress_bar_enabled:
        assert p.pbar is not None
        p.pbar.update(len(tiles_coords))

    # 解码
    if not p.tiled_decode:
        (decoded,) = p.vae_decoder.decode(p.vae, samples)
    else:
        (decoded,) = p.vae_decoder_tiled.decode(p.vae, samples, 512)

    # 将每个解码分块合成回其源图像
    result_imgs = list(images)
    for i, result_img in enumerate(result_imgs):
        for j in range(len(tiles_coords)):
            idx = i * len(tiles_coords) + j
            tile_sampled = tensor_to_pil(decoded, idx)
            initial_tile_size = batch_tiles[idx][1]
            crop_region = batch_crop_regions[idx]
            tile_mask = batch_masks[idx]

            if tile_sampled.size != initial_tile_size:
                tile_sampled = tile_sampled.resize(initial_tile_size, Image.Resampling.LANCZOS)

            image_tile_only = Image.new('RGBA', result_img.size)
            image_tile_only.paste(tile_sampled, crop_region[:2])

            temp = image_tile_only.copy()
            temp.putalpha(tile_mask)
            image_tile_only.paste(temp, image_tile_only)

            result = result_img.convert('RGBA')
            result.alpha_composite(image_tile_only)
            result_img = result.convert('RGB')
            result_imgs[i] = result_img

    return result_imgs


# ═══ ControlNet 补丁裁剪（移植自 crop_model_patch.py）═══
@contextmanager
def crop_model_cond(
    model, crop_regions, init_size, canvas_size, tile_size, latent_crop=False
):
    """
    上下文管理器：裁剪可能包含 ControlNet 提示的模型补丁。

    用法:
        with crop_model_cond(model, ...) as patched_model:
            # 在此使用 patched_model
            ...
    """
    # 克隆可能无用，但由于 ComfyUI commit fe053ba 仍需管理补丁状态变化
    patched_model = model.clone()
    patches = patched_model.model_options.get("transformer_options", {}).get(
        "patches", {}
    )
    applied_croppers = {}
    for module, module_patches in patches.items():
        for patch in module_patches:
            logger.debug(
                f"Processing patch {type(patch).__name__} in module {module} with id {id(patch)}"
            )
            if id(patch) in applied_croppers:
                # 避免同一补丁出现在多个模块时重复裁剪
                logger.debug(
                    f"Skipping patch with id {id(patch)} as it has already been processed"
                )
                continue
            if type(patch).__name__ in ("DiffSynthCnetPatch", "ZImageControlPatch"):
                cropper = ModelPatchCropper(patch).crop(
                    crop_regions, canvas_size, latent_crop
                )
                applied_croppers[id(patch)] = cropper
    try:
        yield patched_model
    finally:
        # 恢复原始模型
        for patch_id, cropper in applied_croppers.items():
            logger.debug(f"Restoring patch with id {patch_id}")
            del cropper


class ModelPatchCropper:
    """
    处理包含 ControlNet 提示的模型补丁裁剪。
    保存原始补丁状态，裁剪后恢复。

    :param patch: 要裁剪的补丁对象
    """

    def __init__(self, patch):
        self.patch = patch
        self.original_state = {
            "image": patch.image.clone(),
            "encoded_image": patch.encoded_image.clone(),
            "encoded_image_size": patch.encoded_image_size,
        }
        self.patch_class = type(patch).__name__
        required_attrs = (
            "image",
            "model_patch",
            "vae",
            "strength",
            "encoded_image",
            "encoded_image_size",
        )
        missing_attrs = [attr for attr in required_attrs if not hasattr(patch, attr)]
        assert not missing_attrs, (
            f"{self.patch_class} is missing required attributes: {', '.join(missing_attrs)}"
        )

    def __del__(self):
        # 删除对象时确保恢复原始状态
        self.patch.image = self.original_state["image"]
        self.patch.encoded_image = self.original_state["encoded_image"]
        self.patch.encoded_image_size = self.original_state["encoded_image_size"]

    def crop(self, crop_regions, canvas_size, latent_crop=True):
        """
        裁剪 ControlNet 补丁图像与潜变量。

        :param patch: ControlNet 补丁（ZImageControlPatch 或 DiffSynthCnetPatch）
        :param crop_regions: 批次中每个分块的 (x1, y1, x2, y2) 裁剪坐标列表
        :param canvas_size: 画布尺寸 (width, height)
        :param latent_crop: True 时直接裁剪编码潜变量（不重新编码），
                            False 时裁剪像素图像并重新通过 VAE 编码
        """
        patch = self.patch
        patch_class = self.patch_class

        # 规范化为区域列表
        if not isinstance(crop_regions, list):
            crop_regions = [crop_regions]

        # 裁剪像素空间图像
        assert len(patch.image.shape) == 4, (
            f"Expected image to have 4 dimensions (b, h, w, c), got {patch.image.shape}"
        )

        # 计算相对图像尺寸的裁剪区域（图像为 [b, h, w, c]）
        image_size = (patch.image.shape[2], patch.image.shape[1])  # (w, h)

        # 为每个区域裁剪并收集
        cropped_images = []
        for crop_region in crop_regions:
            resized_crop = resize_region(crop_region, canvas_size, image_size)
            x1, y1, x2, y2 = resized_crop
            cropped_image = patch.image[:, y1:y2, x1:x2, :]
            cropped_images.append(cropped_image)

        # 沿批次维度拼接所有裁剪图像
        concatenated_image = torch.cat(cropped_images, dim=0)
        logger.debug(
            f"Cropped {patch_class} image from {patch.image.shape} to {concatenated_image.shape}"
        )
        patch.image = concatenated_image
        patch.encoded_image_size = (
            concatenated_image.shape[1],
            concatenated_image.shape[2],
        )

        if latent_crop:
            # 直接裁剪编码潜变量（不重新编码）
            downscale_ratio = patch.vae.spacial_compression_encode()
            # encoded_image 为 [b, c, h, w]，encoded_image_size 为像素空间的 (h, w)
            assert len(patch.encoded_image.shape) == 4, (
                f"Expected encoded_image to have 4 dimensions (b, c, h, w), got {patch.encoded_image.shape}"
            )

            # 为每个区域裁剪潜变量
            cropped_latents = []
            for crop_region in crop_regions:
                resized_crop = resize_region(crop_region, canvas_size, image_size)
                # 将像素裁剪转换为潜空间裁剪
                x1, y1, x2, y2 = tuple(x // downscale_ratio for x in resized_crop)
                cropped_latent = patch.encoded_image[:, :, y1:y2, x1:x2]
                cropped_latents.append(cropped_latent)

            # 沿批次维度拼接所有裁剪潜变量并更新补丁
            patch.encoded_image = torch.cat(cropped_latents, dim=0)
        else:
            # 通过调用 __init__ 重新编码裁剪图像
            # 这将编码 cropped_image 并更新 encoded_image/encoded_image_size
            # ZImageControlPatch 支持 inpaint_image，未来可能需要处理
            patch.__init__(
                patch.model_patch,
                patch.vae,
                concatenated_image,
                patch.strength,
                inpaint_image=patch.inpaint_image,
                mask=patch.mask,
            )

        return self


# ═══ ③ 核心算法（原 usdu_algorithm.py）═══
# 包含：USDUpscaler（放大+分块重绘+接缝修复流程）、USDURedraw（线性/棋盘分块）、
# USDUSeamsFix（带通/半块/半块+交叉点接缝修复）、run_upscale（入口流程）。
# 已融合 usdu_patch.py 的批量分块处理；修复参考实现中接缝修复降噪参数不生效的问题。
class USDUpscaler:

    def __init__(self, p, image, upscaler_index, save_redraw, save_seams_fix, tile_width, tile_height) -> None:
        self.p = p
        self.image = image
        self.scale_factor = math.ceil(max(p.width, p.height) / max(image.width, image.height))
        self.upscaler = sd_upscalers[upscaler_index]
        self.redraw = USDURedraw()
        self.redraw.save = save_redraw
        self.redraw.tile_width = tile_width if tile_width > 0 else tile_height
        self.redraw.tile_height = tile_height if tile_height > 0 else tile_width
        self.seams_fix = USDUSeamsFix()
        self.seams_fix.save = save_seams_fix
        self.seams_fix.tile_width = tile_width if tile_width > 0 else tile_height
        self.seams_fix.tile_height = tile_height if tile_height > 0 else tile_width
        self.initial_info = None
        self.rows = math.ceil(self.p.height / self.redraw.tile_height)
        self.cols = math.ceil(self.p.width / self.redraw.tile_width)

    def get_factor(self, num):
        # 直接返回，无需 elif
        if num == 1:
            return 2
        if num % 4 == 0:
            return 4
        if num % 3 == 0:
            return 3
        if num % 2 == 0:
            return 2
        return 0

    def get_factors(self):
        scales = []
        current_scale = 1
        current_scale_factor = self.get_factor(self.scale_factor)
        while current_scale_factor == 0:
            self.scale_factor += 1
            current_scale_factor = self.get_factor(self.scale_factor)
        while current_scale < self.scale_factor:
            current_scale_factor = self.get_factor(self.scale_factor // current_scale)
            scales.append(current_scale_factor)
            current_scale = current_scale * current_scale_factor
            if current_scale_factor == 0:
                break
        self.scales = enumerate(scales)

    def upscale(self):
        # 输出信息
        print(f"画布尺寸: {self.p.width}x{self.p.height}")
        print(f"图像尺寸: {self.image.width}x{self.image.height}")
        print(f"缩放系数: {self.scale_factor}")
        # 检查放大器是否为空
        if self.upscaler.name == "None":
            self.image = self.image.resize((self.p.width, self.p.height), resample=Image.LANCZOS)
        else:
            # 获取缩放因子列表
            self.get_factors()
            # 按所有因子依次放大图像
            for index, value in self.scales:
                print(f"放大迭代 {index+1}，缩放因子 {value}")
                self.image = self.upscaler.scaler.upscale(self.image, value, self.upscaler.data_path)
            # 缩放到设定尺寸
            self.image = self.image.resize((self.p.width, self.p.height), resample=Image.LANCZOS)
        # 同步 batch 到放大尺寸，保证后续分块重绘基于放大图
        batch[:] = [self.image] + [
            img.resize((self.p.width, self.p.height), resample=Image.LANCZOS)
            for img in batch[1:]
        ]

    def setup_redraw(self, redraw_mode, padding, mask_blur):
        self.redraw.mode = USDUMode(redraw_mode)
        self.redraw.enabled = self.redraw.mode != USDUMode.NONE
        self.redraw.padding = padding
        self.p.mask_blur = mask_blur

    def setup_seams_fix(self, padding, denoise, mask_blur, width, mode):
        self.seams_fix.padding = padding
        self.seams_fix.denoise = denoise
        self.seams_fix.mask_blur = mask_blur
        self.seams_fix.width = width
        self.seams_fix.mode = USDUSFMode(mode)
        self.seams_fix.enabled = self.seams_fix.mode != USDUSFMode.NONE

    def calc_jobs_count(self):
        redraw_job_count = (self.rows * self.cols) if self.redraw.enabled else 0
        seams_job_count = 0
        if self.seams_fix.mode == USDUSFMode.BAND_PASS:
            seams_job_count = self.rows + self.cols - 2
        elif self.seams_fix.mode == USDUSFMode.HALF_TILE:
            seams_job_count = self.rows * (self.cols - 1) + (self.rows - 1) * self.cols
        elif self.seams_fix.mode == USDUSFMode.HALF_TILE_PLUS_INTERSECTIONS:
            seams_job_count = self.rows * (self.cols - 1) + (self.rows - 1) * self.cols + (self.rows - 1) * (self.cols - 1)

        state.job_count = redraw_job_count + seams_job_count

    def print_info(self):
        print(f"分块尺寸: {self.redraw.tile_width}x{self.redraw.tile_height}")
        print(f"分块数量: {self.rows * self.cols}")
        print(f"网格: {self.rows}x{self.cols}")
        print(f"重绘启用: {self.redraw.enabled}")
        print(f"接缝修复模式: {self.seams_fix.mode.name}")

    def add_extra_info(self):
        self.p.extra_generation_params["Ultimate SD upscale upscaler"] = self.upscaler.name
        self.p.extra_generation_params["Ultimate SD upscale tile_width"] = self.redraw.tile_width
        self.p.extra_generation_params["Ultimate SD upscale tile_height"] = self.redraw.tile_height
        self.p.extra_generation_params["Ultimate SD upscale mask_blur"] = self.p.mask_blur
        self.p.extra_generation_params["Ultimate SD upscale padding"] = self.redraw.padding

    def process(self):
        state.begin()
        self.calc_jobs_count()
        self.result_images = []
        if self.redraw.enabled:
            self.image = self.redraw.start(self.p, self.image, self.rows, self.cols)
            self.initial_info = self.redraw.initial_info
        self.result_images.append(self.image)

        if self.seams_fix.enabled:
            self.image = self.seams_fix.start(self.p, self.image, self.rows, self.cols)
            self.initial_info = self.seams_fix.initial_info
            self.result_images.append(self.image)
        state.end()


class USDURedraw:

    def init_draw(self, p, width, height):
        p.inpaint_full_res = True
        p.inpaint_full_res_padding = self.padding
        p.width = math.ceil((self.tile_width + self.padding) / 64) * 64
        p.height = math.ceil((self.tile_height + self.padding) / 64) * 64
        mask = Image.new("L", (width, height), "black")
        draw = ImageDraw.Draw(mask)
        return mask, draw

    def calc_rectangle(self, xi, yi):
        x1 = xi * self.tile_width
        y1 = yi * self.tile_height
        x2 = xi * self.tile_width + self.tile_width
        y2 = yi * self.tile_height + self.tile_height

        return x1, y1, x2, y2

    def linear_process(self, p, image, rows, cols):
        batch_size = getattr(p, 'batch_size', 1)

        if batch_size <= 1:
            # 单块逐个处理
            mask, draw = self.init_draw(p, image.width, image.height)
            processed = None
            for yi in range(rows):
                for xi in range(cols):
                    if state.interrupted:
                        break
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="white")
                    p.init_images = [image]
                    p.image_mask = mask
                    processed = process_images(p)
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="black")
                    if (len(processed.images) > 0):
                        image = processed.images[0]
        else:
            # 批量模式：多个分块一次编码/采样/解码
            self.init_draw(p, image.width, image.height)
            tiles_to_process = []
            for yi in range(rows):
                for xi in range(cols):
                    if state.interrupted:
                        break
                    tiles_to_process.append((xi, yi))
                    if len(tiles_to_process) >= batch_size or (yi == rows - 1 and xi == cols - 1):
                        batch[:] = process_batch_tiles(p, tiles_to_process, batch, self.calc_rectangle)
                        tiles_to_process = []
            image = batch[0]

        p.width = image.width
        p.height = image.height
        self.initial_info = None

        return image

    def chess_process(self, p, image, rows, cols):
        batch_size = getattr(p, 'batch_size', 1)

        if batch_size <= 1:
            # 单块逐个处理（先白后黑两轮）
            mask, draw = self.init_draw(p, image.width, image.height)
            tiles = []
            # 计算分块颜色
            for yi in range(rows):
                for xi in range(cols):
                    if state.interrupted:
                        break
                    if xi == 0:
                        tiles.append([])
                    color = xi % 2 == 0
                    if yi > 0 and yi % 2 != 0:
                        color = not color
                    tiles[yi].append(color)

            processed = None
            for yi in range(len(tiles)):
                for xi in range(len(tiles[yi])):
                    if state.interrupted:
                        break
                    if not tiles[yi][xi]:
                        tiles[yi][xi] = not tiles[yi][xi]
                        continue
                    tiles[yi][xi] = not tiles[yi][xi]
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="white")
                    p.init_images = [image]
                    p.image_mask = mask
                    processed = process_images(p)
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="black")
                    if (len(processed.images) > 0):
                        image = processed.images[0]

            for yi in range(len(tiles)):
                for xi in range(len(tiles[yi])):
                    if state.interrupted:
                        break
                    if not tiles[yi][xi]:
                        continue
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="white")
                    p.init_images = [image]
                    p.image_mask = mask
                    processed = process_images(p)
                    draw.rectangle(self.calc_rectangle(xi, yi), fill="black")
                    if (len(processed.images) > 0):
                        image = processed.images[0]
        else:
            # 批量模式：按棋盘颜色分批处理（先白后黑）
            self.init_draw(p, image.width, image.height)

            # 确定分块"白/黑"顺序
            tile_colors = []
            for yi in range(rows):
                row_colors = []
                for xi in range(cols):
                    color = xi % 2 == 0
                    if yi > 0 and yi % 2 != 0:
                        color = not color
                    row_colors.append(color)
                tile_colors.append(row_colors)

            # 以棋盘顺序迭代：先白后黑
            def chess_order_iter(white):
                for yi in range(rows):
                    for xi in range(cols):
                        if tile_colors[yi][xi] == white:
                            yield (xi, yi)

            # 先处理白色分块再处理黑色分块
            for color in (True, False):
                tiles_to_process = []
                for tx, ty in chess_order_iter(color):
                    if state.interrupted:
                        break
                    tiles_to_process.append((tx, ty))
                    if len(tiles_to_process) >= batch_size:
                        batch[:] = process_batch_tiles(p, tiles_to_process, batch, self.calc_rectangle)
                        tiles_to_process = []
                if tiles_to_process:
                    batch[:] = process_batch_tiles(p, tiles_to_process, batch, self.calc_rectangle)
            image = batch[0]

        p.width = image.width
        p.height = image.height
        self.initial_info = None

        return image

    def start(self, p, image, rows, cols):
        self.initial_info = None
        if self.mode == USDUMode.LINEAR:
            return self.linear_process(p, image, rows, cols)
        if self.mode == USDUMode.CHESS:
            return self.chess_process(p, image, rows, cols)


class USDUSeamsFix:

    def init_draw(self, p):
        self.initial_info = None
        p.width = math.ceil((self.tile_width + self.padding) / 64) * 64
        p.height = math.ceil((self.tile_height + self.padding) / 64) * 64

    def half_tile_process(self, p, image, rows, cols):

        self.init_draw(p)
        processed = None

        gradient = Image.linear_gradient("L")
        row_gradient = Image.new("L", (self.tile_width, self.tile_height), "black")
        row_gradient.paste(gradient.resize(
            (self.tile_width, self.tile_height // 2), resample=Image.BICUBIC), (0, 0))
        row_gradient.paste(gradient.rotate(180).resize(
                (self.tile_width, self.tile_height // 2), resample=Image.BICUBIC),
                (0, self.tile_height // 2))
        col_gradient = Image.new("L", (self.tile_width, self.tile_height), "black")
        col_gradient.paste(gradient.rotate(90).resize(
            (self.tile_width // 2, self.tile_height), resample=Image.BICUBIC), (0, 0))
        col_gradient.paste(gradient.rotate(270).resize(
            (self.tile_width // 2, self.tile_height), resample=Image.BICUBIC), (self.tile_width // 2, 0))

        p.denoise = self.denoise
        p.mask_blur = self.mask_blur

        for yi in range(rows - 1):
            for xi in range(cols):
                if state.interrupted:
                    break
                p.width = self.tile_width
                p.height = self.tile_height
                p.inpaint_full_res = True
                p.inpaint_full_res_padding = self.padding
                mask = Image.new("L", (image.width, image.height), "black")
                mask.paste(row_gradient, (xi * self.tile_width, yi * self.tile_height + self.tile_height // 2))

                p.init_images = [image]
                p.image_mask = mask
                processed = process_images(p)
                if (len(processed.images) > 0):
                    image = processed.images[0]

        for yi in range(rows):
            for xi in range(cols - 1):
                if state.interrupted:
                    break
                p.width = self.tile_width
                p.height = self.tile_height
                p.inpaint_full_res = True
                p.inpaint_full_res_padding = self.padding
                mask = Image.new("L", (image.width, image.height), "black")
                mask.paste(col_gradient, (xi * self.tile_width + self.tile_width // 2, yi * self.tile_height))

                p.init_images = [image]
                p.image_mask = mask
                processed = process_images(p)
                if (len(processed.images) > 0):
                    image = processed.images[0]

        p.width = image.width
        p.height = image.height

        return image

    def half_tile_process_corners(self, p, image, rows, cols):
        fixed_image = self.half_tile_process(p, image, rows, cols)
        processed = None
        self.init_draw(p)
        gradient = Image.radial_gradient("L").resize(
            (self.tile_width, self.tile_height), resample=Image.BICUBIC)
        gradient = ImageOps.invert(gradient)
        p.denoise = self.denoise
        p.mask_blur = self.mask_blur

        for yi in range(rows - 1):
            for xi in range(cols - 1):
                if state.interrupted:
                    break
                p.width = self.tile_width
                p.height = self.tile_height
                p.inpaint_full_res = True
                p.inpaint_full_res_padding = 0
                mask = Image.new("L", (fixed_image.width, fixed_image.height), "black")
                mask.paste(gradient, (xi * self.tile_width + self.tile_width // 2,
                                      yi * self.tile_height + self.tile_height // 2))

                p.init_images = [fixed_image]
                p.image_mask = mask
                processed = process_images(p)
                if (len(processed.images) > 0):
                    fixed_image = processed.images[0]

        p.width = fixed_image.width
        p.height = fixed_image.height

        return fixed_image

    def band_pass_process(self, p, image, cols, rows):

        self.init_draw(p)
        processed = None

        p.denoise = self.denoise
        p.mask_blur = 0

        gradient = Image.linear_gradient("L")
        mirror_gradient = Image.new("L", (256, 256), "black")
        mirror_gradient.paste(gradient.resize((256, 128), resample=Image.BICUBIC), (0, 0))
        mirror_gradient.paste(gradient.rotate(180).resize((256, 128), resample=Image.BICUBIC), (0, 128))

        row_gradient = mirror_gradient.resize((image.width, self.width), resample=Image.BICUBIC)
        col_gradient = mirror_gradient.rotate(90).resize((self.width, image.height), resample=Image.BICUBIC)

        for xi in range(1, rows):
            if state.interrupted:
                break
            p.width = self.width + self.padding * 2
            p.height = image.height
            p.inpaint_full_res = True
            p.inpaint_full_res_padding = self.padding
            mask = Image.new("L", (image.width, image.height), "black")
            mask.paste(col_gradient, (xi * self.tile_width - self.width // 2, 0))

            p.init_images = [image]
            p.image_mask = mask
            processed = process_images(p)
            if (len(processed.images) > 0):
                image = processed.images[0]
        for yi in range(1, cols):
            if state.interrupted:
                break
            p.width = image.width
            p.height = self.width + self.padding * 2
            p.inpaint_full_res = True
            p.inpaint_full_res_padding = self.padding
            mask = Image.new("L", (image.width, image.height), "black")
            mask.paste(row_gradient, (0, yi * self.tile_height - self.width // 2))

            p.init_images = [image]
            p.image_mask = mask
            processed = process_images(p)
            if (len(processed.images) > 0):
                image = processed.images[0]

        p.width = image.width
        p.height = image.height

        return image

    def start(self, p, image, rows, cols):
        if USDUSFMode(self.mode) == USDUSFMode.BAND_PASS:
            return self.band_pass_process(p, image, rows, cols)
        elif USDUSFMode(self.mode) == USDUSFMode.HALF_TILE:
            return self.half_tile_process(p, image, rows, cols)
        elif USDUSFMode(self.mode) == USDUSFMode.HALF_TILE_PLUS_INTERSECTIONS:
            return self.half_tile_process_corners(p, image, rows, cols)
        else:
            return image


def run_upscale(p, tile_width, tile_height, mask_blur, padding, seams_fix_width, seams_fix_denoise, seams_fix_padding,
                seams_fix_mask_blur, seams_fix_type, redraw_mode, custom_scale):
    """Ultimate SD Upscale 入口流程：放大 → 分块重绘 → 接缝修复。

    执行后修改模块级 batch（最新图像批次），返回 USDUpscaler 实例（含 result_images）。
    """
    fix_seed(p)
    torch_gc()

    p.do_not_save_grid = True
    p.do_not_save_samples = True
    p.inpaint_full_res = False

    p.inpainting_fill = 1
    p.n_iter = 1

    seed = p.seed

    # 初始化图像
    init_img = p.init_images[0]
    if init_img is None:
        return Processed(p, [], seed, "Empty image")
    init_img = flatten(init_img, opts.img2img_background_color)

    # 按图像尺寸缩放（target_size_type == 2）
    p.width = math.ceil((init_img.width * custom_scale) / 64) * 64
    p.height = math.ceil((init_img.height * custom_scale) / 64) * 64

    # 放大
    upscaler = USDUpscaler(p, init_img, 0, False, False, tile_width, tile_height)
    upscaler.upscale()
    # 保存放大后、重绘前的图像副本（供节点输出）
    upscaler.upscaled_image = upscaler.image.copy()

    # 分块重绘与接缝修复设置
    upscaler.setup_redraw(redraw_mode, padding, mask_blur)
    upscaler.setup_seams_fix(seams_fix_padding, seams_fix_denoise, seams_fix_mask_blur, seams_fix_width, seams_fix_type)
    upscaler.print_info()
    upscaler.add_extra_info()
    upscaler.process()

    return upscaler


# ═══ ④ 节点定义（原 usdu_upscale.py）═══
# 重绘模式：中文选项 → USDUMode 枚举
重绘模式映射 = {
    "线性": USDUMode.LINEAR,
    "棋盘": USDUMode.CHESS,
    "无": USDUMode.NONE,
}

# 接缝修复模式：中文选项 → USDUSFMode 枚举
接缝修复模式映射 = {
    "无": USDUSFMode.NONE,
    "带通": USDUSFMode.BAND_PASS,
    "半块": USDUSFMode.HALF_TILE,
    "半块+交叉点": USDUSFMode.HALF_TILE_PLUS_INTERSECTIONS,
}


class ShouWangUltimateSDUp:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "节点束": ("PIPE_LINE",),
            "图像": ("IMAGE",),
            "放大倍数": ("FLOAT", {"default": 2, "min": 0.05, "max": 4, "step": 0.05}),
            "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "迭代步数": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "采样器": (comfy.samplers.KSampler.SAMPLERS,),
            "调度器": (comfy.samplers.KSampler.SCHEDULERS,),
            "降噪": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
            "放大模型": ("UPSCALE_MODEL",),
            "重绘模式": (list(重绘模式映射.keys()), {"default": "线性"}),
            "分块宽度": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 8}),
            "分块高度": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 8}),
            "遮罩羽化": ("INT", {"default": 8, "min": 0, "max": 64, "step": 1}),
            "分块填充": ("INT", {"default": 32, "min": 0, "max": 8192, "step": 8}),
            "接缝修复模式": (list(接缝修复模式映射.keys()), {"default": "无"}),
            "接缝修复降噪": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "接缝修复宽度": ("INT", {"default": 64, "min": 0, "max": 8192, "step": 8}),
            "接缝修复遮罩羽化": ("INT", {"default": 8, "min": 0, "max": 64, "step": 1}),
            "接缝修复填充": ("INT", {"default": 16, "min": 0, "max": 8192, "step": 8}),
            "统一分块": ("BOOLEAN", {"default": True}),
            "分块解码": ("BOOLEAN", {"default": False}),
            "批量大小": ("INT", {"default": 1, "min": 1, "max": 4096}),
        },
        "optional": {
            "模型": ("MODEL",),
            "正面条件": ("CONDITIONING",),
            "负面条件": ("CONDITIONING",),
            "vae": ("VAE",),
        }}

    RETURN_TYPES = ("PIPE_LINE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("节点束", "结果图像", "放大图像")
    FUNCTION = "upscale"
    CATEGORY = "守望🐢/采样器"

    def upscale(self, pipe=None, image=None, 放大倍数=2, 随机种子=0, 迭代步数=20, cfg=8.0, 采样器=None, 调度器=None,
                降噪=0.2, 放大模型=None, 重绘模式="线性", 分块宽度=512, 分块高度=512, 遮罩羽化=8, 分块填充=32,
                接缝修复模式="无", 接缝修复降噪=1.0, 接缝修复宽度=64, 接缝修复遮罩羽化=8, 接缝修复填充=16,
                统一分块=True, 分块解码=False, 批量大小=1,
                model=None, positive=None, negative=None, vae=None):
        # 从 PIPE_LINE 束中提取模型/条件/VAE/CLIP，未单独连接时自动取用束内数据
        clip = None
        if pipe is not None:
            if model is None:
                model = pipe.get("model")
            if positive is None:
                positive = pipe.get("positive")
            if negative is None:
                negative = pipe.get("negative")
            if vae is None:
                vae = pipe.get("vae")
            clip = pipe.get("clip")

        redraw_mode = 重绘模式映射[重绘模式]
        seam_fix_mode = 接缝修复模式映射[接缝修复模式]

        assert 批量大小 == 1 or 统一分块, "批量大小大于 1 时需开启统一分块，批次中所有分块必须同尺寸"

        # 设置共享状态：放大器、图像批次（合并后为模块级变量，赋值需 global 声明）
        global actual_upscaler, batch_as_tensor
        sd_upscalers[0] = UpscalerData()
        actual_upscaler = 放大模型
        batch[:] = [tensor_to_pil(image, i) for i in range(len(image))]
        batch_as_tensor = image

        # 构建处理对象
        p = StableDiffusionProcessing(
            batch[0], model, positive, negative, vae,
            随机种子, 迭代步数, cfg, 采样器, 调度器, 降噪, 放大倍数, 统一分块, 分块解码,
            分块宽度, 分块高度, redraw_mode, seam_fix_mode,
            batch_size=批量大小,
        )

        # 执行放大 → 分块重绘 → 接缝修复
        upscaler = run_upscale(p, 分块宽度, 分块高度, 遮罩羽化, 分块填充, 接缝修复宽度,
                               接缝修复降噪, 接缝修复填充, 接缝修复遮罩羽化,
                               seam_fix_mode, redraw_mode, 放大倍数)

        # 最终结果与放大（重绘前）图像
        final_image = pil_to_tensor(batch[0])
        upscaled_image = pil_to_tensor(upscaler.upscaled_image)

        out_pipe = {
            "model": model,
            "positive": positive,
            "negative": negative,
            "vae": vae,
            "clip": clip,
            "images": final_image,
            "loader_settings": {
                "seed": 随机种子, "steps": 迭代步数, "cfg": cfg,
                "sampler_name": 采样器, "scheduler": 调度器, "denoise": 降噪,
            },
        }
        return (out_pipe, final_image, upscaled_image)


NODE_CLASS_MAPPINGS = {
    "ShouWangUltimateSDUp": ShouWangUltimateSDUp,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangUltimateSDUp": "守望-UltimateSDUpscale🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
