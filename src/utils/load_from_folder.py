import hashlib
import os
import random

import numpy as np
import torch
from PIL import Image, ImageOps

from comfy.cli_args import args


class LoadFromFolder:
    """从文件夹加载图像（参考 KJNodes LoadImagesFromFolderKJ 简化，保持原尺寸）：
    - 文件夹支持绝对路径或相对 ComfyUI 根目录的路径，每次运行只加载一张图片
    - 「加载模式」可选顺序加载（始终输出起始序号对应的那张）、随机加载（每次执行随机选一张）
      或按序号顺序加载（每次运行输出起始序号对应的图像，序号自动 +1 跨运行推进）
    - 起始序号从 1 开始标记第一张图，大于文件夹图片总数时运行报错
    - 可选包含子文件夹
    - IS_CHANGED 按文件列表与修改时间做缓存，文件夹未变化时不重复执行（随机/按序号模式每次重新执行）
    """

    VALID_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tga"]
    folder_hashes = {}  # 文件夹内容指纹缓存
    sequence_state = {}  # 按序号顺序加载的跨运行推进状态 {(文件夹, 起始序号, 包含子文件夹): 下次输出序号}
    file_map = {}  # 输出张量 id -> 文件路径，供保存节点空前缀时还原原文件名（只保留最近 100 条）

    @classmethod
    def _collect_files(cls, folder: str, include_subfolders: bool):
        files = []
        if include_subfolders:
            for root, _, names in os.walk(folder):
                for name in names:
                    if any(name.lower().endswith(ext) for ext in cls.VALID_EXTENSIONS):
                        files.append(os.path.join(root, name))
        else:
            for name in sorted(os.listdir(folder)):
                if any(name.lower().endswith(ext) for ext in cls.VALID_EXTENSIONS):
                    files.append(os.path.join(folder, name))
        return sorted(files)

    @classmethod
    def IS_CHANGED(cls, 文件夹, **kwargs):
        if 文件夹 and not os.path.isabs(文件夹) and args.base_directory:
            文件夹 = os.path.join(args.base_directory, 文件夹)
        if not 文件夹 or not os.path.isdir(文件夹):
            return float("NaN")

        file_data = []
        for path in cls._collect_files(文件夹, kwargs.get("包含子文件夹", False)):
            try:
                file_data.append((path, os.path.getmtime(path)))
            except OSError:
                pass

        combined = hashlib.md5()
        combined.update(文件夹.encode("utf-8"))
        combined.update(str(len(file_data)).encode("utf-8"))
        for path, mtime in file_data:
            combined.update(f"{path}:{mtime}".encode("utf-8"))
        current_hash = combined.hexdigest()

        # 随机/按序号顺序加载模式：每次执行都重新执行，不做缓存
        if kwargs.get("加载模式", "顺序加载") in ("随机加载", "按序号顺序加载"):
            return float("NaN")

        old_hash = cls.folder_hashes.get(文件夹)
        cls.folder_hashes[文件夹] = current_hash
        return old_hash if old_hash == current_hash else current_hash

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "文件夹": ("STRING", {"default": ""}),
            },
            "optional": {
                "加载模式": (["顺序加载", "随机加载", "按序号顺序加载"], {"default": "顺序加载"}),
                "包含子文件夹": ("BOOLEAN", {"default": False}),
                "起始序号": ("INT", {"default": 1, "min": 1, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("图像", "数量", "文件路径")
    FUNCTION = "load_from_folder"
    CATEGORY = "守望🐢/工具"
    DESCRIPTION = "从文件夹每次加载一张图片：加载模式可选顺序/随机/按序号顺序，起始序号 1 表示第一张图（大于图片总数会报错），文件夹填绝对路径或相对 ComfyUI 根目录的路径。"

    @staticmethod
    def _load_image(path: str):
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        return torch.from_numpy(np.array(img).astype(np.float32) / 255.0)[None,]

    @staticmethod
    def _record_file(image, path):
        """记录输出张量与源文件路径的映射（供保存节点原名还原），限制大小防止无限增长"""
        cls = LoadFromFolder
        cls.file_map[id(image)] = path
        if len(cls.file_map) > 100:
            cls.file_map = dict(list(cls.file_map.items())[-50:])

    def load_from_folder(self, 文件夹, 加载模式="顺序加载", 包含子文件夹=False, 起始序号=0):
        if 文件夹 and not os.path.isabs(文件夹) and args.base_directory:
            文件夹 = os.path.join(args.base_directory, 文件夹)
        if not 文件夹 or not os.path.isdir(文件夹):
            raise FileNotFoundError(f"文件夹 '{文件夹}' 不存在")

        paths = self._collect_files(文件夹, 包含子文件夹)
        total = len(paths)
        if total == 0:
            raise FileNotFoundError(f"文件夹 '{文件夹}' 中没有可加载的图像文件")
        # 兼容旧工作流保存的 0：0 视为 1（第一张图）
        起始序号 = max(1, int(起始序号))
        if 起始序号 > total:
            raise ValueError(
                f"起始序号({起始序号}) 大于文件夹中的图像数量({total})：文件夹 '{文件夹}'，起始序号 1 表示第一张图"
            )

        if 加载模式 == "按序号顺序加载":
            # 每次运行输出序号对应的图像，序号自动 +1 跨运行推进，到末尾后回绕到第一张
            key = (文件夹, 起始序号, 包含子文件夹)
            idx = self.sequence_state.get(key, 起始序号)
            if idx < 1 or idx > total:
                idx = 1  # 防御：状态异常时回到第一张
            path = paths[idx - 1]
            self.sequence_state[key] = idx + 1 if idx < total else 1
            image = self._load_image(path)
            self._record_file(image, path)
            return (image, 1, [path])

        if 加载模式 == "随机加载":
            path = random.choice(paths)  # 每次执行随机选一张，配合 IS_CHANGED 返回 NaN 确保每次重选
        else:
            path = paths[起始序号 - 1]  # 顺序加载：始终输出起始序号对应的那张
        image = self._load_image(path)
        self._record_file(image, path)
        return (image, 1, [path])


NODE_CLASS_MAPPINGS = {
    "ShouWangLoadFromFolder": LoadFromFolder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangLoadFromFolder": "守望-从文件夹加载🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
