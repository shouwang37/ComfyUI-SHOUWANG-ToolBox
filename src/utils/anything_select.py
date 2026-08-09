from typing import Any, Dict, Tuple

# 通配符类型，支持所有 ComfyUI 数据类型（含插件自定义类型）
class AnyType(str):
    """仅覆盖 __ne__ 使其恒为 False，配合 ComfyUI validate_node_input 的类型匹配逻辑；
    不能定义 __eq__，否则会触发 Python 规则将 __hash__ 置为 None，导致实例不可哈希而崩溃。
    """
    def __ne__(self, __value: object) -> bool:
        return False


any_type = AnyType("*")


class AnythingSelect:
    """自适应输入端口选择器：
    - 输入端口数量由「输入数量」参数控制（1~99，前端 web/anything_select.js 同步端口增减）
    - 输出端口固定 1 个，按「切换模式」输出：顺序取第一个非空输入，或按「选择序号」取指定输入
    - 类型锁定：从第一个已连接输入出发，沿连接链递归追溯真实类型（如 IMAGE，
      支持切换器串联穿透），其余输入端口与输出端口同步锁定为该类型，只能接入同类型数据
    """
    MAX_INPUTS = 99  # 输入端口上限，与 web/anything_select.js 中的 MAX _INPUTS 保持一致
    DEFAULT_COUNT = 5  # 默认输入端口数量

    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        input_types = {
            "required": {
                "切换模式": (["顺序", "选择"], {"default": "顺序"}),
                # 上限仅作后端兜底，实际上限由前端按「输入数量」动态同步
                "选择序号": ("INT", {"default": 1, "min": 1, "max": cls.MAX_INPUTS, "step": 1}),
                "输入数量": ("INT", {"default": cls.DEFAULT_COUNT, "min": 1, "max": cls.MAX_INPUTS, "step": 1}),
            },
            "optional": {},
        }
        # 后端声明全部端口，前端按参数动态显示（保证前后端端口名一致）
        # 统一命名「输入{i}」（无下划线）；带下划线旧名由 _get_input 兼容查询兜底
        for i in range(1, cls.MAX_INPUTS + 1):
            input_types["optional"][f"输入{i}"] = (any_type, {"forceInput": True})
        return input_types

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("输出",)
    FUNCTION = "select_output"
    OUTPUT_NODE = False
    CATEGORY = "守望🐢/工具"

    def _is_empty(self, value) -> bool:
        """判断输入是否为空：None、空字符串、空容器、空节点束（EasyUse PIPE_LINE）均视为空"""
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, tuple)) and len(value) == 0:
            return True
        if isinstance(value, dict):
            if len(value) == 0:
                return True
            # EasyUse 节点束（PIPE_LINE / CONTEXT）：所有字段均为 None 视为空
            if 'model' in value and 'clip' in value:
                return all(v is None for v in value.values())
        return False

    def _get_input(self, kwargs: Dict[str, Any], i: int) -> Any:
        """读取输入值：优先规范命名「输入{i}」，兼容历史命名「输入_{i}」（旧端口）"""
        value = kwargs.get(f"输入{i}")
        if value is None:
            value = kwargs.get(f"输入_{i}")
        return value

    def select_output(self, **kwargs) -> Tuple[Any]:
        """按「切换模式」输出：
        - 顺序：取第一个非空输入（输入_1 为空/未接入则自动取输入_2，依此类推）
        - 选择：按「选择序号」直接取对应输入（输入_序号）
        所有输入均为空时抛出明确错误：避免将 None 传给下游节点（如 PreviewImage）
        导致 'NoneType' object is not subscriptable 的隐性崩溃"""
        if kwargs.get("切换模式", "顺序") == "选择":
            index = kwargs.get("选择序号", 1)
            value = self._get_input(kwargs, index)
            if self._is_empty(value):
                raise ValueError(
                    f"守望-任意切换器：「选择」模式选中的 输入_{index} 为空"
                    "（未连接或值为空），请连接有效输入或调整选择序号。"
                )
            return (value,)
        for i in range(1, self.MAX_INPUTS + 1):
            value = self._get_input(kwargs, i)
            if not self._is_empty(value):
                return (value,)
        # 诊断信息：列出实际收到的输入参数，便于定位端口名不匹配问题
        received = [
            f"{k}={type(v).__name__}{'(空)' if self._is_empty(v) else ''}"
            for k, v in kwargs.items()
            if k not in ("切换模式", "选择序号", "输入数量")
        ]
        raise ValueError(
            "守望-任意切换器：所有输入均为空（未连接或值为空），"
            "请至少连接一个有效输入后再运行。"
            f"当前收到的输入参数：{', '.join(received) or '无'}"
        )


NODE_CLASS_MAPPINGS = {
    "ShouWangAnythingSelect": AnythingSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangAnythingSelect": "守望-任意切换器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
