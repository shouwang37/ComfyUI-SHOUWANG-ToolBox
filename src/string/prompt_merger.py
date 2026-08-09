from typing import Any, Dict, Tuple


class PromptMerger:
    """守望-提示词合并器：多个提示词输入，按连接符号拼接为一个提示词
    - 输入端口数量由「输入数量」参数控制（1~99，前端 web/prompt_merger.js 同步端口增减）
    - 「连接符号」为输入框，默认英文逗号，可供用户更改（如 ", "）
    - 空输入自动跳过，不参与拼接
    """

    MAX_INPUTS = 99  # 输入端口上限，与 web/prompt_merger.js 中的 MAX_INPUTS 保持一致
    DEFAULT_COUNT = 1  # 默认输入端口数量

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        input_types = {
            "required": {
                "输入数量": ("INT", {"default": cls.DEFAULT_COUNT, "min": 1, "max": cls.MAX_INPUTS, "step": 1}),
                "连接符号": ("STRING", {"default": ","}),
            },
            "optional": {},
        }
        # 后端声明全部端口，前端按参数动态显示（保证前后端端口名一致）
        # forceInput：纯输入端口，不生成节点上的多行文本框 widget
        for i in range(1, cls.MAX_INPUTS + 1):
            input_types["optional"][f"提示词{i}"] = ("STRING", {"forceInput": True})
        return input_types

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词输出",)
    FUNCTION = "merge"
    CATEGORY = "守望🐢/提示词"

    def _get_input(self, kwargs: Dict[str, Any], i: int) -> Any:
        """读取输入值：优先规范命名「提示词{i}」，兼容历史命名「输入_{i}」「输入{i}」（旧版端口）"""
        value = kwargs.get(f"提示词{i}")
        if value is None:
            value = kwargs.get(f"输入_{i}")
        if value is None:
            value = kwargs.get(f"输入{i}")
        return value

    def merge(self, 输入数量: int, 连接符号: str, **kwargs) -> Tuple[str]:
        """按输入数量收集非空输入，用连接符号拼接为提示词"""
        parts: list = []
        for i in range(1, 输入数量 + 1):
            value = self._get_input(kwargs, i)
            if value is None:
                continue
            if isinstance(value, str):
                if value.strip() == "":
                    continue
                parts.append(value.strip())
            else:
                parts.append(value)
        return (连接符号.join(parts),)


NODE_CLASS_MAPPINGS = {
    "ShouWangPromptMerger": PromptMerger,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangPromptMerger": "守望-提示词合并器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
