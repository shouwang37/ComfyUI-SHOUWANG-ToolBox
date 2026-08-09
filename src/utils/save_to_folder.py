import json
import os

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths
from comfy.cli_args import args


class SaveToFolder:
    """保存图像至指定文件夹（参考 KJNodes SaveImageKJ 简化）：
    - 文件夹支持绝对路径（不存在自动创建）或相对 output 目录的路径
    - 支持 png / jpg / webp 三种格式，png 附带工作流元数据
    - 文件名前缀为空时自动使用原文件名命名（图像来自「守望-从文件夹加载」节点时），已存在自动加序号
    """

    def __init__(self):
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "文件名前缀": ("STRING", {"default": ""}),
                "文件夹": ("STRING", {"default": "output"}),
                "格式": (["png", "jpg", "webp"], {"default": "png"}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文件路径",)
    FUNCTION = "save_to_folder"
    OUTPUT_NODE = True
    CATEGORY = "守望🐢/工具"
    DESCRIPTION = "将图像保存到指定文件夹：文件夹填绝对路径，或相对 output 目录的路径（如 output/test）；文件名前缀为空时自动使用原文件名命名（图像来自「守望-从文件夹加载」节点）。"

    @staticmethod
    def _unique_path(folder: str, base: str, ext: str):
        """已存在同名文件时自动追加 _1、_2 序号"""
        file = f"{base}.{ext}"
        filepath = os.path.join(folder, file)
        i = 1
        while os.path.exists(filepath):
            filepath = os.path.join(folder, f"{base}_{i}.{ext}")
            i += 1
        return filepath

    def save_to_folder(self, 图像, 文件名前缀="", 文件夹="output", 格式="png", prompt=None, extra_pnginfo=None):
        if os.path.isabs(文件夹):
            full_output_folder = 文件夹
            os.makedirs(full_output_folder, exist_ok=True)
        else:
            full_output_folder = folder_paths.get_output_directory()

        # 文件名前缀为空时，从「从文件夹加载」节点的张量映射中还原原文件名（去扩展名，换当前格式扩展名）
        use_original_name = not str(文件名前缀).strip()
        if use_original_name:
            from src.utils.load_from_folder import LoadFromFolder

            src_path = LoadFromFolder.file_map.get(id(图像))
            if not src_path:
                raise ValueError(
                    "文件名前缀为空且无法获取图像原文件名："
                    "请填写文件名前缀，或使用「守望-从文件夹加载」节点的图像输出"
                )
            base_name = os.path.splitext(os.path.basename(src_path))[0] or "image"
        else:
            base_name = 文件名前缀

        _, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            base_name, full_output_folder, 图像[0].shape[1], 图像[0].shape[0]
        )

        # png 格式写入工作流元数据（jpg / webp 不写）
        metadata = None
        if 格式 == "png" and not args.disable_metadata:
            metadata = PngInfo()
            if prompt is not None:
                metadata.add_text("prompt", json.dumps(prompt))
            if extra_pnginfo is not None:
                for key in extra_pnginfo:
                    metadata.add_text(key, json.dumps(extra_pnginfo[key]))

        saved_paths = []
        for image in 图像:
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            if use_original_name:
                # 原名模式：直接原名命名，同名自动加 _1、_2
                filepath = self._unique_path(full_output_folder, base_name, 格式)
            else:
                file = f"{filename}_{counter:05}.{格式}"
                filepath = os.path.join(full_output_folder, file)
                counter += 1
            if 格式 == "png":
                img.save(filepath, pnginfo=metadata, compress_level=self.compress_level)
            else:
                img.save(filepath, quality=95)
            saved_paths.append(filepath)

        # 返回最后一张的完整路径，便于后续节点引用
        return (saved_paths[-1],)


NODE_CLASS_MAPPINGS = {
    "ShouWangSaveToFolder": SaveToFolder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangSaveToFolder": "守望-保存至文件夹🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
