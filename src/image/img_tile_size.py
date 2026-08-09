import torch


class ShouWangTileImageSize:
    """分块尺寸计算节点：按「宽度/高度因子 + 重叠率」计算单块分块尺寸。
    - 重叠率为 0 时：分块 = 原图尺寸 ÷ 因子（向上取整到 8 的倍数）
    - 重叠率 > 0 时：分块 = 原图尺寸 ÷ (1 + (因子-1) × (1-重叠率))（向下取整到 8 的倍数）
    - 因子为 1 时该方向不切分，分块尺寸 = 原图尺寸
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "宽度因子": ("INT", {"default": 3, "min": 1, "max": 10, "step": 1}),
                "高度因子": ("INT", {"default": 3, "min": 1, "max": 10, "step": 1}),
                "重叠率": ("FLOAT", {"default": 0.1, "min": 0.00, "max": 0.95, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("分块宽度", "分块高度")
    FUNCTION = "compute_tile_size"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "按宽度/高度因子与重叠率计算分块尺寸，供图像分块批处理节点使用（8 的倍数对齐）。"

    def compute_tile_size(self, 图像, 宽度因子, 高度因子, 重叠率):
        _, raw_H, raw_W, _ = 图像.shape
        if 重叠率 == 0:
            # 水平方向
            if 宽度因子 == 1:
                block_width = raw_W
            else:
                block_width = int(raw_W / 宽度因子)
                if block_width % 8 != 0:
                    block_width = ((block_width + 7) // 8) * 8
            # 垂直方向
            if 高度因子 == 1:
                block_height = raw_H
            else:
                block_height = int(raw_H / 高度因子)
                if block_height % 8 != 0:
                    block_height = ((block_height + 7) // 8) * 8
        else:
            # 水平方向（有重叠时总跨度 = 首块 + (因子-1) 块 × (1-重叠率)）
            if 宽度因子 == 1:
                block_width = raw_W
            else:
                block_width = int(raw_W / (1 + (宽度因子 - 1) * (1 - 重叠率)))
                if block_width % 8 != 0:
                    block_width = (block_width // 8) * 8
            # 垂直方向
            if 高度因子 == 1:
                block_height = raw_H
            else:
                block_height = int(raw_H / (1 + (高度因子 - 1) * (1 - 重叠率)))
                if block_height % 8 != 0:
                    block_height = (block_height // 8) * 8

        return (block_width, block_height)


NODE_CLASS_MAPPINGS = {
    "ShouWangTileImageSize": ShouWangTileImageSize,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangTileImageSize": "守望-TTP图像划分尺寸🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

# 本套插件版权所属B站@灵仙儿和二狗子，仅供学习交流使用，未经授权禁止一切商业性质使用
