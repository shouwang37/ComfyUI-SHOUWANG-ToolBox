import os

import torch
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from aiohttp import web

from server import PromptServer

MAX_GROUPS = 9  # 组数上限，与 web/img_splice_comparison.js 中 MAX_GROUPS 保持一致

# 「标题字体」下拉为空时的占位选项
NO_FONT_PLACEHOLDER = "(无字体文件)"

# 支持的字体扩展名（PIL FreeType 加载），扫描字体文件夹时按此筛选
FONT_FILE_EXTENSIONS = (".ttf", ".otf", ".ttc")

# 缩放算法选项（PIL Resampling）→ 等比例缩放时使用
RESAMPLE_METHODS = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "box": Image.Resampling.BOX,
    "hamming": Image.Resampling.HAMMING,
    "lanczos": Image.Resampling.LANCZOS,
}


def _register_font_files_route():
    """注册前端刷新字体下拉列表的路由；PromptServer 未实例化（非 ComfyUI 启动环境）时跳过"""
    server_instance = getattr(PromptServer, "instance", None)
    if server_instance is None:
        return

    @server_instance.routes.get("/shouwang/font_files")
    async def _shouwang_font_files(request):
        """返回 assets/fonts 文件夹中的字体文件名"""
        return web.json_response({"files": ImageSpliceComparison._list_font_files()})


_register_font_files_route()


def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


def _hex_to_rgb(hex_str: str, default=(0, 0, 0)) -> tuple:
    """解析 '#RRGGBB' / '#RRGGBBAA' 颜色字符串（忽略 alpha），失败返回默认黑色"""
    s = hex_str.strip().lstrip("#")
    try:
        if len(s) == 6:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        if len(s) == 8:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        pass
    return default


class ImageSpliceComparison:
    """多图对比拼接节点：N 组（图像+标题）按方向拼接为一张图。
    - 组数动态关联输入端口与标题输入框（前端 web/img_splice_comparison.js 同步增减）
    - 标题可以为空但图像必须输入；每图四周扩展「间距宽度」的底色区域，标题绘制在扩展区域内
    - 「标题字体」下拉选择插件目录 assets/fonts 中的字体文件，加载失败回退默认字体
    """

    @classmethod
    def INPUT_TYPES(cls):
        font_files = cls._list_font_files() or [NO_FONT_PLACEHOLDER]
        input_types = {
            "required": {
                "组数": ("INT", {"default": 2, "min": 1, "max": MAX_GROUPS, "step": 1}),
                "方向": (["左到右", "右到左", "上到下", "下到上"], {"default": "左到右"}),
                "匹配图像尺寸": ("BOOLEAN", {"default": True}),
                "间距宽度": ("INT", {"default": 10, "min": 0, "step": 1}),
                "间距颜色": ("STRING", {"default": "#000000"}),
                "标题位置": (["上方", "下方"], {"default": "上方"}),
                "标题颜色": ("STRING", {"default": "#FFFFFF"}),
                "标题字体": (font_files, {"default": font_files[0]}),
                "标题字号": ("INT", {"default": 128, "min": 1, "step": 1}),
                "缩放算法": (list(RESAMPLE_METHODS), {"default": "lanczos"}),
            },
            "optional": {},
        }
        # 后端声明全部组端口（图像N、标题N 交替），前端按「组数」动态显示
        # forceInput 强制标题为端口而非输入框
        for i in range(1, MAX_GROUPS + 1):
            input_types["optional"][f"图像{i}"] = ("IMAGE",)
            input_types["optional"][f"标题{i}"] = ("STRING", {"forceInput": True})
        return input_types

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("拼接结果",)
    FUNCTION = "splice_images"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "多组图像按方向拼接为对比图：每组可带标题（可为空），支持匹配尺寸、间距底色、本地字体。"

    @staticmethod
    def _font_folder() -> str:
        """字体文件夹（唯一）：插件目录下的 assets/fonts"""
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(plugin_dir, "assets", "fonts")

    @staticmethod
    def _list_font_files() -> list:
        """扫描字体文件夹，返回按名称排序的字体文件名列表（文件夹不存在返回空）"""
        folder = ImageSpliceComparison._font_folder()
        if not os.path.isdir(folder):
            return []
        return sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith(FONT_FILE_EXTENSIONS)
        )

    @staticmethod
    def _load_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """加载字体：按文件名在 assets/fonts 中查找；兼容旧工作流中的直接路径；失败回退默认字体"""
        font_name = (font_name or "").strip()
        candidates = []
        if font_name and font_name != NO_FONT_PLACEHOLDER:
            candidates.append(os.path.join(ImageSpliceComparison._font_folder(), font_name))
            if os.path.isfile(font_name):  # 旧工作流可能直接存了文件路径
                candidates.append(font_name)
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, ValueError):
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # 旧版 PIL 不支持 size 参数
            return ImageFont.load_default()

    @staticmethod
    def _pad_with_title(img: Image.Image, title: str, padding: int, font, title_pos: str, bg_color: tuple,
                        text_color: tuple, stroke_color: tuple) -> Image.Image:
        """为单图扩展四周底色区域；标题侧扩展高度自动容纳标题，标题绘制在该区域内"""
        w, h = img.size
        # 标题侧扩展高度：有标题时至少容纳字号+留白；无标题时与其余三边一致
        title_side = max(padding, font.size + 6) if title else padding
        if title_pos == "上方":
            top, bottom = title_side, padding
        else:
            top, bottom = padding, title_side

        canvas = Image.new("RGB", (w + padding * 2, h + top + bottom), bg_color)
        canvas.paste(img, (padding, top))

        if title:
            draw = ImageDraw.Draw(canvas)
            bbox = draw.textbbox((0, 0), title, font=font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            title_center_y = top // 2 if title_pos == "上方" else canvas.height - bottom // 2
            x = (canvas.width - text_w) // 2 - bbox[0]
            y = title_center_y - text_h // 2 - bbox[1]
            # 标题文字用「标题颜色」，描边用其反色，任意底色下均可辨识
            draw.text((x, y), title, font=font, fill=text_color, stroke_width=2, stroke_fill=stroke_color)
        return canvas

    def splice_images(self, 组数, 方向, 匹配图像尺寸, 间距宽度, 间距颜色, 标题位置, 标题颜色, 标题字体, 标题字号, 缩放算法="lanczos", **kwargs):
        # 收集各组（图像必须输入，未连接的组跳过；标题端口可为空）
        groups = []
        for i in range(1, 组数 + 1):
            image = kwargs.get(f"图像{i}")
            if image is None:
                continue
            title = kwargs.get(f"标题{i}") or ""
            groups.append((tensor2pil(image), title.strip()))
        if not groups:
            raise ValueError("至少需要输入一组图像")

        bg_color = _hex_to_rgb(间距颜色)

        # 匹配图像尺寸：等比例缩放（保持宽高比不变，不拉伸变形）
        # 横向拼接（左到右/右到左）以最高图的高度为基准统一高度，纵向拼接以最宽图的宽度为基准统一宽度
        if 匹配图像尺寸:
            resample = RESAMPLE_METHODS.get(缩放算法, Image.Resampling.LANCZOS)
            if 方向 in ("左到右", "右到左"):
                target = max(img.height for img, _ in groups)
                matched = []
                for img, title in groups:
                    if img.height == target:
                        matched.append((img, title))
                        continue
                    new_h = target
                    new_w = max(1, round(img.width * target / img.height))
                    matched.append((img.resize((new_w, new_h), resample), title))
                groups = matched
            else:  # 上到下/下到上：统一宽度
                target = max(img.width for img, _ in groups)
                matched = []
                for img, title in groups:
                    if img.width == target:
                        matched.append((img, title))
                        continue
                    new_w = target
                    new_h = max(1, round(img.height * target / img.width))
                    matched.append((img.resize((new_w, new_h), resample), title))
                groups = matched

        font = self._load_font(标题字体, 标题字号)
        text_color = _hex_to_rgb(标题颜色, default=(255, 255, 255))
        stroke_color = tuple(255 - c for c in text_color)  # 描边取反色，保证对比

        # 逐组扩展间距区域并绘制标题
        panels = [self._pad_with_title(img, title, 间距宽度, font, 标题位置, bg_color, text_color, stroke_color)
                  for img, title in groups]

        # 按方向拼接：横向/纵向排列，顺序受「右到左」「下到上」反向控制
        if 方向 in ("左到右", "右到左"):
            if 方向 == "右到左":
                panels.reverse()
            total_w = sum(p.width for p in panels)
            total_h = max(p.height for p in panels)
            canvas = Image.new("RGB", (total_w, total_h), bg_color)
            x = 0
            for p in panels:
                canvas.paste(p, (x, (total_h - p.height) // 2))
                x += p.width
        else:
            if 方向 == "下到上":
                panels.reverse()
            total_h = sum(p.height for p in panels)
            total_w = max(p.width for p in panels)
            canvas = Image.new("RGB", (total_w, total_h), bg_color)
            y = 0
            for p in panels:
                canvas.paste(p, ((total_w - p.width) // 2, y))
                y += p.height

        return (pil2tensor(canvas),)


NODE_CLASS_MAPPINGS = {
    "ShouWangImageSpliceComparison": ImageSpliceComparison,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageSpliceComparison": "守望-图像拼接对比🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']