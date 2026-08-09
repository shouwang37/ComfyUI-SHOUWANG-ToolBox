import re
from typing import Tuple


class PromptFormatter:
    """守望-提示词格式器：格式化提示词文本（下划线转空格、中文逗号转英文逗号、转义括号）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "源提示词": ("STRING", {"multiline": True, "default": ""}),
                "下划线转空格": ("BOOLEAN", {"default": True}),
                "中文逗号转英文": ("BOOLEAN", {"default": True}),
                "转义括号": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    FUNCTION = "format"
    CATEGORY = "守望🐢/提示词"

    def format(self, 源提示词: str, 下划线转空格: bool, 中文逗号转英文: bool, 转义括号: bool) -> Tuple[str]:
        """格式化提示词文本，返回处理后的提示词"""
        text = 源提示词 or ""

        # 下划线替换为空格
        if 下划线转空格:
            text = text.replace("_", " ")

        # 中文逗号替换为英文逗号（连同后面空白统一为 ", "）
        if 中文逗号转英文:
            text = re.sub(r'，\s*', ', ', text)

        # 转义括号，但保留 ComfyUI 权重格式 (内容:数值)；已转义的括号（前面带反斜杠）不再重复转义
        if 转义括号:
            # 按权重格式分割（捕获组使匹配内容保留在列表中），仅对普通文本部分转义
            parts = re.split(r'(\([^()]+:\d+(?:\.\d+)?\))', text)
            for i, part in enumerate(parts):
                if i % 2 == 0:  # 普通文本（奇数索引为权重格式，原样保留）
                    # 仅转义未被转义的括号：(?<!\\) 表示前面没有反斜杠
                    part = re.sub(r'(?<!\\)\(', r'\(', part)
                    part = re.sub(r'(?<!\\)\)', r'\)', part)
                    parts[i] = part
            text = ''.join(parts)

        return (text.strip(),)


NODE_CLASS_MAPPINGS = {
    "ShouWangPromptFormatter": PromptFormatter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangPromptFormatter": "守望-提示词格式器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
