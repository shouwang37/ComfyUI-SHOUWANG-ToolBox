import torch
from PIL import Image
import numpy as np


def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


class ShouWangImageTileBatch:
    """图像分块批处理节点：按分块尺寸将单张图像切分为带重叠的分块批量。
    - 输出分块批量（IMAGE）、每个分块在原图中的位置（LIST）、原图尺寸（TUPLE）、网格行列数（TUPLE）
    - 分块数量按「(尺寸 + 分块 - 1) // 分块」计算，重叠量自动均分；边缘分块不足时回退对齐到末尾
    - 输出可与「守望-图像分块拼接」直接对接
    """

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "分块宽度": ("INT", {"default": 1024, "min": 1}),
                "分块高度": ("INT", {"default": 1024, "min": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "LIST", "TUPLE", "TUPLE")
    RETURN_NAMES = ("分块图像", "位置", "原始尺寸", "网格大小")
    FUNCTION = "tile_image"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "将单张图像按指定分块尺寸切分为带重叠的分块批量，输出分块、位置、原图尺寸与网格大小。"

    def tile_image(self, 图像, 分块宽度=1024, 分块高度=1024):
        image = tensor2pil(图像.squeeze(0))
        img_width, img_height = image.size

        if img_width <= 分块宽度 and img_height <= 分块高度:
            return (pil2tensor(image), [(0, 0, img_width, img_height)], (img_width, img_height), (1, 1))

        def calculate_step(size, block_size):
            if size <= block_size:
                return 1, 0
            else:
                num_blocks = (size + block_size - 1) // block_size
                overlap = (num_blocks * block_size - size) // (num_blocks - 1)
                step = block_size - overlap
                return num_blocks, step

        num_cols, step_x = calculate_step(img_width, 分块宽度)
        num_rows, step_y = calculate_step(img_height, 分块高度)

        tiles = []
        positions = []
        for y in range(num_rows):
            for x in range(num_cols):
                left = x * step_x
                upper = y * step_y
                right = min(left + 分块宽度, img_width)
                lower = min(upper + 分块高度, img_height)

                if right - left < 分块宽度:
                    left = max(0, img_width - 分块宽度)
                if lower - upper < 分块高度:
                    upper = max(0, img_height - 分块高度)

                tile = image.crop((left, upper, right, lower))
                tile_tensor = pil2tensor(tile)
                tiles.append(tile_tensor)
                positions.append((left, upper, right, lower))

        tiles = torch.stack(tiles, dim=0).squeeze(1)
        return (tiles, positions, (img_width, img_height), (num_cols, num_rows))


NODE_CLASS_MAPPINGS = {
    "ShouWangImageTileBatch": ShouWangImageTileBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageTileBatch": "守望-TTP图像分块处理🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# 本套插件版权所属B站@灵仙儿和二狗子，仅供学习交流使用，未经授权禁止一切商业性质使用