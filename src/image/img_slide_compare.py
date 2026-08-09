from nodes import PreviewImage


class ImageSlideCompare(PreviewImage):
    """图像滑动对比节点：接收两张图像，在节点内通过鼠标滑动分割线对比。
    参考 rgthree-comfy 的 Image Comparer 实现，仅保留核心滑动对比能力
    （忽略多组选择、禁用、书签等附加功能）。
    - 图像保存到临时目录（继承 PreviewImage），由前端 web/img_slide_compare.js 拉取展示
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "图像A": ("IMAGE",),
                "图像B": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    FUNCTION = "compare"
    CATEGORY = "守望🐢/图像"
    DESCRIPTION = "两张图像滑动分割线对比：鼠标悬停节点左右移动，分割线左侧显示图像B、右侧显示图像A"

    def compare(self, 图像A=None, 图像B=None, filename_prefix="shouwang/compare", prompt=None, extra_pnginfo=None):
        """保存两组图像供前端对比展示，返回 UI 数据（a_images / b_images）"""
        result = {"ui": {"a_images": [], "b_images": []}}
        if 图像A is not None and len(图像A) > 0:
            result["ui"]["a_images"] = self.save_images(图像A, filename_prefix, prompt, extra_pnginfo)["ui"]["images"]
        if 图像B is not None and len(图像B) > 0:
            result["ui"]["b_images"] = self.save_images(图像B, filename_prefix, prompt, extra_pnginfo)["ui"]["images"]
        return result


NODE_CLASS_MAPPINGS = {
    "ShouWangImageSlideCompare": ImageSlideCompare,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangImageSlideCompare": "守望-图像滑动对比🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
