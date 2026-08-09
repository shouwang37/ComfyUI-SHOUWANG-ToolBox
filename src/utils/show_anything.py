"""守望-展示任何节点：接收任意类型输入，在节点上展示其内容，并透传输出。

参考 ComfyUI-Easy-Use 的 easy showAnything 节点实现（经典 API 风格）：
- 任意类型端口 (\"*\")，任何节点都可接入
- 输出节点（OUTPUT_NODE），执行后前端将文本渲染为只读多行输入框
- 返回内容同时写回工作流数据，保存工作流时可保留展示内容
"""

import json
import os
import time

import numpy as np
import torch
from PIL import Image

import folder_paths


class ShowAnything:
    """「展示任何」调试节点：任意输入 → 节点上显示文本/JSON/图像预览，适合查看中间结果。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "输入": ("*",),  # 任意类型端口，任何节点都可接入
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("输出",)
    FUNCTION = "show"
    OUTPUT_NODE = True  # 末端展示节点：执行结果直接显示在画布上
    CATEGORY = "守望🐢/工具"
    DESCRIPTION = "接收任意类型输入并在节点上展示其内容（字符串/数字/列表/JSON/图像预览），适合调试工作流；同时透传输出。"

    @staticmethod
    def _save_temp_images(tensor: torch.Tensor) -> list:
        """把图像张量保存为临时 PNG，返回 ComfyUI 可预览的文件列表（含尺寸信息）"""
        temp_dir = folder_paths.get_temp_directory()
        os.makedirs(temp_dir, exist_ok=True)

        t = tensor.detach().cpu().float()
        # 统一规范化为 [B,H,W,C]：兼容标准 IMAGE、[B,C,H,W]、灰度 [B,H,W]、单张 [H,W]/[H,W,C]
        if t.ndim == 4:
            if t.shape[-1] not in (1, 3, 4) and t.shape[1] in (1, 3, 4):
                t = t.permute(0, 2, 3, 1)  # [B,C,H,W] → [B,H,W,C]
        elif t.ndim == 3:
            if t.shape[-1] in (1, 3, 4):  # 单张 [H,W,C]
                t = t.unsqueeze(0)
            else:  # 灰度批量 [B,H,W] → [B,H,W,1]
                t = t.unsqueeze(-1)
        else:  # 单张灰度 [H,W]
            t = t.unsqueeze(0).unsqueeze(-1)  # → [1,H,W,1]

        results = []
        for i in range(t.shape[0]):
            arr = np.clip(t[i].numpy() * 255.0, 0, 255).astype(np.uint8)  # [H,W,C]
            if arr.shape[-1] == 1:
                pil = Image.fromarray(arr[:, :, 0], mode="L")
            elif arr.shape[-1] == 4:
                pil = Image.fromarray(arr, mode="RGBA")
            else:
                pil = Image.fromarray(arr, mode="RGB")
            filename = f"show_any_{time.time_ns()}_{i}.png"
            pil.save(os.path.join(temp_dir, filename), compress_level=1)
            results.append({
                "filename": filename,
                "subfolder": "",
                "type": "temp",
                "width": pil.width,
                "height": pil.height,
            })
        return results

    def show(self, 输入=None, unique_id=None, extra_pnginfo=None):
        values = []
        images = []
        if 输入 is not None:
            if isinstance(输入, torch.Tensor) and 输入.ndim >= 3:
                # 图像张量：保存为临时图片供节点预览，文本区显示尺寸描述
                images = self._save_temp_images(输入)
                if images:
                    values.append(f"图像预览：{len(images)} 张，{images[0]['width']}x{images[0]['height']}")
                else:
                    values.append(str(输入))
            elif isinstance(输入, str):
                values.append(输入)
            elif isinstance(输入, (int, float, bool)):
                values.append(str(输入))
            elif isinstance(输入, list) and len(输入) <= 30:
                values = 输入
            else:
                try:
                    values.append(json.dumps(输入, indent=4, ensure_ascii=False))
                except Exception:
                    try:
                        values.append(str(输入))
                    except Exception:
                        raise ValueError("输入存在但无法序列化")

        # 写回工作流节点数据，使保存工作流时保留本次展示内容
        if extra_pnginfo and isinstance(extra_pnginfo, dict) and "workflow" in extra_pnginfo:
            uid = unique_id[0] if isinstance(unique_id, list) else unique_id
            node = next((x for x in extra_pnginfo["workflow"]["nodes"] if str(x["id"]) == str(uid)), None)
            if node:
                node["widgets_values"] = [values]

        result = values[0] if len(values) == 1 else values
        ui = {"text": values}
        if images:
            ui["images"] = images
        return {"ui": ui, "result": (result,)}


NODE_CLASS_MAPPINGS = {
    "ShouWangShowAnything": ShowAnything,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangShowAnything": "守望-预览任何🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
