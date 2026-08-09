import torch
from PIL import Image
import numpy as np


class ShouWangResizeByEdge:
    """按长边/短边缩放图像（保持宽高比）。
    分辨率模式：目标边为指定像素值（px）；倍数模式：目标边为当前分辨率按倍数缩放。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "基准边": (["长边", "短边"], {"default": "长边"}),
                "模式": (["分辨率", "倍数"], {"default": "分辨率"}),
                "分辨率": ("INT", {"default": 1024, "min": 1, "max": 16384, "step": 1}),
                "倍数": ("FLOAT", {"default": 2.0, "min": 0.01, "max": 64.0, "step": 0.1}),
                "缩放方法": (["lanczos", "bicubic", "bilinear", "nearest"], {"default": "lanczos"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "resize"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "按长边/短边缩放图像（保持宽高比）：分辨率模式目标边为指定像素(px)；倍数模式目标边为当前分辨率×倍数。"

    _RESAMPLE = {
        "lanczos": Image.Resampling.LANCZOS,
        "bicubic": Image.Resampling.BICUBIC,
        "bilinear": Image.Resampling.BILINEAR,
        "nearest": Image.Resampling.NEAREST,
    }

    def resize(self, image, 基准边, 模式, 分辨率, 倍数, 缩放方法):
        resample = self._RESAMPLE[缩放方法]
        images = []
        changed = False
        for i in range(image.shape[0]):
            h, w = int(image[i].shape[0]), int(image[i].shape[1])
            edge = max(h, w) if 基准边 == "长边" else min(h, w)
            target = float(分辨率) if 模式 == "分辨率" else edge * 倍数
            scale = target / edge
            new_w = max(1, round(w * scale))
            new_h = max(1, round(h * scale))
            if new_w == w and new_h == h:
                images.append(image[i])
                continue
            changed = True
            channels = int(image[i].shape[2])
            arr = np.clip(255.0 * image[i].cpu().numpy(), 0, 255).astype(np.uint8)
            if channels == 1:
                pil = Image.fromarray(arr[:, :, 0], mode="L")
            elif channels == 4:
                pil = Image.fromarray(arr, mode="RGBA")
            else:
                pil = Image.fromarray(arr, mode="RGB")
            pil = pil.resize((new_w, new_h), resample)
            out = torch.from_numpy(np.array(pil).astype(np.float32) / 255.0)
            if channels == 1:
                out = out.unsqueeze(-1)  # 灰度回补通道维 [H,W] → [H,W,1]
            images.append(out)
        if not changed:
            return (image,)
        return (torch.stack(images),)


NODE_CLASS_MAPPINGS = {
    "ShouWangResizeByEdge": ShouWangResizeByEdge,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangResizeByEdge": "守望-图像按边缩放🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
