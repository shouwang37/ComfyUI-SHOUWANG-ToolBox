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


class PromptFilter:
    """守望-提示词批量过滤器：从源提示词中批量删除指定的词组"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "源提示词": ("STRING", {"multiline": True, "default": ""}),
                "删去词组": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    FUNCTION = "filter"
    CATEGORY = "守望🐢/提示词"

    def filter(self, 源提示词: str, 删去词组: str) -> Tuple[str]:
        """批量删除源提示词中指定的词组，返回过滤后的提示词"""
        if not 源提示词:
            return ("",)

        tags_list = split_tags(源提示词)

        # 删除操作
        if 删去词组:
            delete_list = split_tags(删去词组)
            tags_list = [tag for tag in tags_list if tag not in delete_list]

        return (", ".join(tags_list),)


NODE_CLASS_MAPPINGS = {
    "ShouWangPromptFilter": PromptFilter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangPromptFilter": "守望-提示词批量过滤器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
