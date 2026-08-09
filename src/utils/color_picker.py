"""守望-取色器节点：前端方形色板选色，输出纯色图片与颜色值。

交互（前端 canvas 实现，参考 PS 取色器）：
- 方形色域：横轴饱和度、纵轴明度（上亮下暗），下方色相渐变滑条
- 点击/拖拽选色，颜色经隐藏的「颜色值」widget 传入后端
- 「随机颜色」开启时后端忽略前端颜色，随机生成并回传前端同步显示
- 输出该颜色的纯色图片（宽×高）与颜色值字符串（RGB / 十六进制）
"""

import random

import numpy as np
import torch


class ShouWangColorPicker:
    """「取色器」节点：方形色板选色 → 输出纯色图片与颜色值。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "宽": ("INT", {"default": 512, "min": 1, "max": 8192, "step": 1}),
                "高": ("INT", {"default": 512, "min": 1, "max": 8192, "step": 1}),
                "颜色类型": (["十六进制", "RGB"], {"default": "十六进制"}),
                "随机颜色": ("BOOLEAN", {"default": False}),
                # 前端取色器隐藏传值（r,g,b 逗号分隔），随机模式下忽略
                "颜色值": ("STRING", {"default": "255,0,0", "multiline": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图片", "颜色值")
    FUNCTION = "pick"
    CATEGORY = "守望🐢/工具"
    DESCRIPTION = "方形取色器（参考PS）：点击色域/色相滑条选色，输出该颜色的纯色图片与颜色值（RGB 或十六进制）。"

    @staticmethod
    def _parse_color(text: str) -> tuple:
        """解析前端颜色值 "r,g,b"，容错并钳制到 0~255，非法时回退红色。"""
        try:
            parts = [int(p.strip()) for p in str(text).split(",") if p.strip() != ""]
            if len(parts) < 3:
                raise ValueError
            return tuple(max(0, min(255, c)) for c in parts[:3])
        except Exception:
            return (255, 0, 0)

    @staticmethod
    def _format_color(r: int, g: int, b: int, color_type: str) -> str:
        """按「颜色类型」格式化颜色值字符串：RGB → "255,0,0"，十六进制 → "#FF0000"。"""
        if color_type == "十六进制":
            return "#{:02X}{:02X}{:02X}".format(r, g, b)
        return f"{r},{g},{b}"

    def pick(self, 宽, 高, 颜色类型, 随机颜色, 颜色值="255,0,0"):
        # 解析前端颜色；随机模式覆盖为随机 RGB
        r, g, b = self._parse_color(颜色值)
        if 随机颜色:
            r, g, b = random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)

        # 生成纯色图片 [1, H, W, 3]
        arr = np.full((高, 宽, 3), (r, g, b), dtype=np.float32) / 255.0
        image = torch.from_numpy(arr).unsqueeze(0)

        text = self._format_color(r, g, b, 颜色类型)
        # 回传实际颜色给前端（随机模式下同步取色器显示）
        return {"ui": {"color": [f"{r},{g},{b}"]}, "result": (image, text)}


NODE_CLASS_MAPPINGS = {
    "ShouWangColorPicker": ShouWangColorPicker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangColorPicker": "守望-取色器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
