import torch
import numpy as np
from PIL import Image


class ShouWangImageFormat:
    """「守望-图像格式化」：将图像长宽向上对齐到指定最小倍数（默认 16），
    统一不同分辨率图像的尺寸规格，便于图像模型学习/训练使用。
    如 1234×987 → 1248×1008（倍数 16）；已对齐时原样输出，不额外缩放。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "缩放算法": (["lanczos", "bicubic", "bilinear", "nearest"], {"default": "lanczos"}),
                "最小倍数": (["4", "8", "16", "32", "64", "128"], {"default": "16"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "format"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "将图像长宽向上对齐到指定最小倍数（默认 16）：如 1234×987 → 1248×1008，统一不同分辨率图像的尺寸规格，便于图像模型学习。已对齐时原样输出。"

    _RESAMPLE = {
        "lanczos": Image.Resampling.LANCZOS,
        "bicubic": Image.Resampling.BICUBIC,
        "bilinear": Image.Resampling.BILINEAR,
        "nearest": Image.Resampling.NEAREST,
    }

    def format(self, 图像, 缩放算法, 最小倍数):
        multiple = int(最小倍数)
        resample = self._RESAMPLE[缩放算法]
        images = []
        changed = False
        for i in range(图像.shape[0]):
            h, w = int(图像[i].shape[0]), int(图像[i].shape[1])
            # 向上取整到 multiple 的倍数（不裁剪，仅补齐到最小对齐尺寸）
            new_w = ((w + multiple - 1) // multiple) * multiple
            new_h = ((h + multiple - 1) // multiple) * multiple
            if new_w == w and new_h == h:
                images.append(图像[i])
                continue
            changed = True
            channels = int(图像[i].shape[2])
            arr = np.clip(255.0 * 图像[i].cpu().numpy(), 0, 255).astype(np.uint8)
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
            return (图像,)
        return (torch.stack(images),)


NODE_CLASS_MAPPINGS = {
    "ShouWangImageFormat": ShouWangImageFormat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageFormat": "守望-图像格式化🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
