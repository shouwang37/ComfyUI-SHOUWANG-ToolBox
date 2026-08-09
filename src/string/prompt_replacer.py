import re
from typing import List, Tuple


def split_tags(tags_str: str) -> List[str]:
    """按中英文逗号、换行分割提示词字符串，并去除空格

    兼容 multiline 文本框每行一个标签的用法。
    """
    if not tags_str:
        return []
    tags = re.split(r'[,，\r\n]+', tags_str)
    # 去除空格和空字符串
    return [tag.strip() for tag in tags if tag.strip()]


def replace_tags(tags_list: List[str], original_list: List[str], replacement_list: List[str]) -> List[str]:
    """执行提示词替换操作，支持一换一、一换多、多换一和多换多的替换模式

    替换规则：
    - 一换一: 等长列表按位置一一对应替换
    - 一换多: 1个原标签 → N个替换标签 (len(original)==1, len(replacement)>1)
    - 多换一: N个原标签 → 1个替换标签 (len(original)>1, len(replacement)==1)
    - 多换多: 等长列表按位置映射
    - 如果原列表比替换列表长，多余的原标签会被删除（替换为空）
    - 如果替换列表比原列表长（非一换多模式），多余的替换标签会被忽略
    """
    if not original_list:
        return tags_list[:]

    # 构建替换映射：每个原标签 → 替换标签列表
    mapping: dict = {}

    if len(original_list) == 1 and len(replacement_list) > 1:
        # 一换多模式：单个原标签映射到所有替换标签
        mapping[original_list[0]] = replacement_list[:]
    elif len(original_list) > 1 and len(replacement_list) == 1:
        # 多换一模式：多个原标签都映射到同一个替换标签
        for orig in original_list:
            mapping[orig] = replacement_list[:]
    else:
        # 默认：按位置一一对应映射；原标签没有对应替换项 → 替换为空（删除）
        for idx, orig in enumerate(original_list):
            if idx < len(replacement_list):
                mapping[orig] = [replacement_list[idx]]
            else:
                mapping[orig] = []

    # 应用映射
    result = []
    for tag in tags_list:
        if tag in mapping:
            result.extend(mapping[tag])
        else:
            result.append(tag)

    return result


class PromptReplacer:
    """守望-提示词替换器：将源提示词中的指定词替换为新词（支持一换一/一换多/多换一/多换多）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "源提示词": ("STRING", {"multiline": True, "default": ""}),
                "原替换单一词组": ("STRING", {"multiline": True, "default": ""}),
                "替换为单一词组": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    FUNCTION = "replace"
    CATEGORY = "守望🐢/提示词"

    def replace(self, 源提示词: str, 原替换单一词组: str, 替换为单一词组: str) -> Tuple[str]:
        """替换源提示词中的指定词组，返回处理后的提示词"""
        if not 源提示词:
            return ("",)

        tags_list = split_tags(源提示词)

        # 替换操作
        if 原替换单一词组 and 替换为单一词组:
            original_list = split_tags(原替换单一词组)
            replacement_list = split_tags(替换为单一词组)
            tags_list = replace_tags(tags_list, original_list, replacement_list)

        return (", ".join(tags_list),)


NODE_CLASS_MAPPINGS = {
    "ShouWangPromptReplacer": PromptReplacer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangPromptReplacer": "守望-提示词替换器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
