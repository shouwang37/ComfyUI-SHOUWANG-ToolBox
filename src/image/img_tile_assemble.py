import torch
from PIL import Image
import numpy as np


def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


class ShouWangImageAssy:
    """图像分块拼接节点：将分块批量按位置信息拼接还原为原图。
    - 输入「分块图像/位置/原始尺寸/网格大小」直接对接「守望-图像分块批处理」
    - 填充值 > 0 时对重叠区做渐变混合（平滑过渡），= 0 时直接拼接
    """

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "分块图像": ("IMAGE",),
                "位置": ("LIST",),
                "原始尺寸": ("TUPLE",),
                "网格大小": ("TUPLE",),
                "填充值": ("INT", {"default": 64, "min": 0}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("拼接/重组后的图像",)
    FUNCTION = "assemble_image"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "将图像分块批处理节点输出的分块按位置信息拼接还原为原图，重叠区支持渐变混合。"

    def create_gradient_mask(self, size, direction):
        """创建用于混合的渐变遮罩。"""
        mask = Image.new("L", size)
        for i in range(size[0] if direction == 'horizontal' else size[1]):
            value = int(255 * (1 - (i / size[0] if direction == 'horizontal' else i / size[1])))
            if direction == 'horizontal':
                mask.paste(value, (i, 0, i+1, size[1]))
            else:
                mask.paste(value, (0, i, size[0], i+1))
        return mask

    def blend_tiles(self, tile1, tile2, overlap_size, direction, padding):
        """以平滑过渡混合两个分块的重叠区域。"""
        blend_size = padding
        if blend_size > overlap_size:
            blend_size = overlap_size

        if blend_size == 0:
            # 无混合：按正确重叠量直接拼接
            if direction == 'horizontal':
                result = Image.new("RGB", (tile1.width + tile2.width - overlap_size, tile1.height))
                # 粘贴 tile1 除去重叠部分的左侧区域
                result.paste(tile1.crop((0, 0, tile1.width - overlap_size, tile1.height)), (0, 0))
                # 重叠起始处直接粘贴 tile2
                result.paste(tile2, (tile1.width - overlap_size, 0))
            else:
                # 垂直方向
                result = Image.new("RGB", (tile1.width, tile1.height + tile2.height - overlap_size))
                result.paste(tile1.crop((0, 0, tile1.width, tile1.height - overlap_size)), (0, 0))
                result.paste(tile2, (0, tile1.height - overlap_size))
            return result

        # 以下为混合代码，当 blend_size > 0 时执行
        offset_total = overlap_size - blend_size
        offset_left = offset_total // 2
        offset_right = offset_total - offset_left

        size = (blend_size, tile1.height) if direction == 'horizontal' else (tile1.width, blend_size)
        mask = self.create_gradient_mask(size, direction)

        if direction == 'horizontal':
            crop_tile1 = tile1.crop((tile1.width - overlap_size + offset_left, 0, tile1.width - offset_right, tile1.height))
            crop_tile2 = tile2.crop((offset_left, 0, offset_left + blend_size, tile2.height))
            if crop_tile1.size != crop_tile2.size:
                raise ValueError(f"Crop sizes do not match: {crop_tile1.size} vs {crop_tile2.size}")

            blended = Image.composite(crop_tile1, crop_tile2, mask)
            result = Image.new("RGB", (tile1.width + tile2.width - overlap_size, tile1.height))
            result.paste(tile1.crop((0, 0, tile1.width - overlap_size + offset_left, tile1.height)), (0, 0))
            result.paste(blended, (tile1.width - overlap_size + offset_left, 0))
            result.paste(tile2.crop((offset_left + blend_size, 0, tile2.width, tile2.height)), (tile1.width - offset_right, 0))
        else:
            offset_total = overlap_size - blend_size
            offset_top = offset_total // 2
            offset_bottom = offset_total - offset_top

            size = (tile1.width, blend_size)
            mask = self.create_gradient_mask(size, direction)

            crop_tile1 = tile1.crop((0, tile1.height - overlap_size + offset_top, tile1.width, tile1.height - offset_bottom))
            crop_tile2 = tile2.crop((0, offset_top, tile2.width, offset_top + blend_size))
            if crop_tile1.size != crop_tile2.size:
                raise ValueError(f"Crop sizes do not match: {crop_tile1.size} vs {crop_tile2.size}")

            blended = Image.composite(crop_tile1, crop_tile2, mask)
            result = Image.new("RGB", (tile1.width, tile1.height + tile2.height - overlap_size))
            result.paste(tile1.crop((0, 0, tile1.width, tile1.height - overlap_size + offset_top)), (0, 0))
            result.paste(blended, (0, tile1.height - overlap_size + offset_top))
            result.paste(tile2.crop((0, offset_top + blend_size, tile2.width, tile2.height)), (0, tile1.height - offset_bottom))
        return result

    def assemble_image(self, 分块图像, 位置, 原始尺寸, 网格大小, 填充值):
        num_cols, num_rows = 网格大小
        reconstructed_image = Image.new("RGB", 原始尺寸)

        # 第一步：逐行独立混合
        row_images = []
        for row in range(num_rows):
            row_image = tensor2pil(分块图像[row * num_cols].unsqueeze(0))
            for col in range(1, num_cols):
                index = row * num_cols + col
                block_image = tensor2pil(分块图像[index].unsqueeze(0))
                prev_right = 位置[index - 1][2]
                left = 位置[index][0]
                overlap_width = prev_right - left
                if overlap_width > 0:
                    row_image = self.blend_tiles(row_image, block_image, overlap_width, 'horizontal', 填充值)
                else:
                    # 调整 row_image 尺寸以容纳新分块
                    new_width = row_image.width + block_image.width
                    new_height = max(row_image.height, block_image.height)
                    new_row_image = Image.new("RGB", (new_width, new_height))
                    new_row_image.paste(row_image, (0, 0))
                    new_row_image.paste(block_image, (row_image.width, 0))
                    row_image = new_row_image
            row_images.append(row_image)

        # 第二步：逐行垂直混合
        final_image = row_images[0]
        for row in range(1, num_rows):
            prev_lower = 位置[(row - 1) * num_cols][3]
            upper = 位置[row * num_cols][1]
            overlap_height = prev_lower - upper
            if overlap_height > 0:
                final_image = self.blend_tiles(final_image, row_images[row], overlap_height, 'vertical', 填充值)
            else:
                # 调整 final_image 尺寸以容纳新行图像
                new_width = max(final_image.width, row_images[row].width)
                new_height = final_image.height + row_images[row].height
                new_final_image = Image.new("RGB", (new_width, new_height))
                new_final_image.paste(final_image, (0, 0))
                new_final_image.paste(row_images[row], (0, final_image.height))
                final_image = new_final_image

        return (pil2tensor(final_image),)


NODE_CLASS_MAPPINGS = {
    "ShouWangImageAssy": ShouWangImageAssy,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageAssy": "守望-TTP图像分块拼接🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# 本套插件版权所属B站@灵仙儿和二狗子，仅供学习交流使用，未经授权禁止一切商业性质使用
