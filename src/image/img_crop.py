import torch
from PIL import Image
import numpy as np


def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


class EGTXZZCJNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入图像": ("IMAGE",),
                "输入遮罩": ("MASK",),
            },
            "optional": {
                "上": ("INT", {"default": 0, "min": 0}),
                "下": ("INT", {"default": 0, "min": 0}),
                "左": ("INT", {"default": 0, "min": 0}),
                "右": ("INT", {"default": 0, "min": 0}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "COORDS")
    RETURN_NAMES = ("裁剪图像", "裁剪遮罩", "裁剪数据")
    FUNCTION = "mask_crop"
    CATEGORY = "守望🐢/图像"

    def mask_crop(self, 输入图像, 输入遮罩, 上=0, 下=0, 左=0, 右=0):
        image_pil = tensor2pil(输入图像)
        mask_pil = tensor2pil(输入遮罩)

        mask_array = np.array(mask_pil) > 0

        coords = np.where(mask_array)
        if coords[0].size == 0 or coords[1].size == 0:
            return (输入图像, None, 输入图像)

        x0, y0, x1, y1 = coords[1].min(), coords[0].min(), coords[1].max(), coords[0].max()

        x0 -= 左
        y0 -= 上
        x1 += 右
        y1 += 下

        x0 = max(x0, 0)
        y0 = max(y0, 0)
        x1 = min(x1, image_pil.width)
        y1 = min(y1, image_pil.height)

        cropped_image_pil = image_pil.crop((x0, y0, x1, y1))
        cropped_mask_pil = mask_pil.crop((x0, y0, x1, y1))
        cropped_image_tensor = pil2tensor(cropped_image_pil)
        cropped_mask_tensor = pil2tensor(cropped_mask_pil)
        return (cropped_image_tensor, cropped_mask_tensor, (y0, y1, x0, x1))


NODE_CLASS_MAPPINGS = {
    "ShouWangMaskCrop": EGTXZZCJNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangMaskCrop": "守望-图像裁剪🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# 本套插件版权所属B站@灵仙儿和二狗子，仅供学习交流使用，未经授权禁止一切商业性质使用
