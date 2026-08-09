import torch
from PIL import Image
import numpy as np

def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

class EGCJPJNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入原图": ("IMAGE",),
                "输入裁剪图像": ("IMAGE",),
                "输入裁剪数据": ("COORDS",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("拼接结果图",)
    FUNCTION = "resize_and_paste"
    CATEGORY = "守望🐢/图像"

    def resize_and_paste(self, 输入原图, 输入裁剪图像, 输入裁剪数据):
        original_image_pil = tensor2pil(输入原图)
        cropped_image_pil = tensor2pil(输入裁剪图像)

        if 输入裁剪数据 is None:
            return (输入原图,)

        y0, y1, x0, x1 = 输入裁剪数据

        target_width = x1 - x0
        target_height = y1 - y0

        cropped_image_pil = cropped_image_pil.resize((target_width, target_height))

        original_image_pil.paste(cropped_image_pil, (x0, y0))

        pasted_image_tensor = pil2tensor(original_image_pil)

        return (pasted_image_tensor,)

NODE_CLASS_MAPPINGS = {
    "ShouWangImageStitch": EGCJPJNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageStitch": "守望-图像拼接🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# 本套插件版权所属B站@灵仙儿和二狗子，仅供学习交流使用，未经授权禁止一切商业性质使用
