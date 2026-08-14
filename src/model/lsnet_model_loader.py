"""守望-LSNet模型加载器:从 models/lsnet/<模型文件夹> 加载 LSNet 画师风格分类模型。

参考 comfyui-lsnet 的 LSNet Model Loader 节点移植,模型包结构保持原样:
- 模型目录:ComfyUI/models/lsnet/<模型文件夹>/,内含 best_checkpoint.pth、class_mapping.csv、config.json
- 模型类型自动从 config.json 读取(lsnet_t/s/b/l/xl_artist 等),缺省为 lsnet_xl_artist
- 输出 LSNET_MODEL 模型包(模型 + 预处理 transform + 类别映射 + 设备),供守望-LSNet风格反推器使用
"""

import json
import os

import torch

import folder_paths
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform
from timm.models import create_model

# 统一通过 lsnet_model 包导入(模型定义在 src/model/lsnet_model/__init__.py 中汇总注册)
from src.model.lsnet_model import lsnet_artist  # noqa: F401  导入即注册模型到 timm
from src.model.lsnet_model.lsnet_artist import default_cfgs_artist  # noqa: E402


def load_checkpoint_state(checkpoint_path: str):
    """加载 checkpoint 并返回模型权重"""
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
    if isinstance(checkpoint, dict):
        if 'model' in checkpoint:
            return checkpoint['model']
        if 'model_ema' in checkpoint:
            return checkpoint['model_ema']
    return checkpoint


def normalize_state_dict_keys(state_dict):
    """移除分布式训练前缀等冗余标记"""
    normalized = {}
    for key, value in state_dict.items():
        if key.startswith('module.'):
            new_key = key[len('module.'):]
        else:
            new_key = key
        normalized[new_key] = value
    return normalized


def resolve_num_classes(num_classes_arg, class_mapping, state_dict) -> int:
    """根据参数、CSV 或 checkpoint 推断类别数"""
    # 优先使用CSV中的类别数
    if class_mapping:
        csv_classes = len(class_mapping)
        if num_classes_arg is not None and num_classes_arg != csv_classes:
            print(f"[Warning] 提供的 num_classes={num_classes_arg} 与 CSV 中的类别数 {csv_classes} 不一致，已使用 CSV 的值。")
        return csv_classes

    # 如果没有CSV，使用参数
    if num_classes_arg is not None:
        return num_classes_arg

    # 最后尝试从权重中解析分类头大小
    for key, value in state_dict.items():
        if key.endswith('head.weight') or key.endswith('head.l.weight'):
            return value.shape[0]

    raise ValueError('无法推断 num_classes，请提供 CSV 映射文件或显式指定 num_classes 参数。')


def resolve_feature_dim(feature_dim_arg, state_dict) -> int:
    """根据参数或 checkpoint 推断特征维度"""
    if feature_dim_arg is not None:
        return feature_dim_arg

    # 尝试从权重中解析特征维度
    # 查找head.bn.weight的维度，这通常是特征维度
    for key, value in state_dict.items():
        if key.endswith('head.bn.weight'):
            return value.shape[0]

    # 如果找不到，尝试查找其他可能的特征维度指示器
    for key, value in state_dict.items():
        if 'head' in key and 'weight' in key and len(value.shape) >= 2:
            # 对于线性层，输入维度通常是特征维度
            return value.shape[1] if len(value.shape) > 1 else value.shape[0]

    # 默认值
    print("[Warning] 无法从checkpoint推断特征维度，使用默认值384")
    return 384


def load_class_mapping(class_csv_path):
    """加载 CSV 类别映射，返回 class_id -> name 的字典"""
    if not class_csv_path:
        return None

    import csv
    from pathlib import Path

    csv_path = Path(class_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Class mapping CSV not found: {csv_path}")

    with csv_path.open('r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'class_id' not in reader.fieldnames or 'class_name' not in reader.fieldnames:
            raise ValueError('CSV 必须包含 class_id 和 class_name 两列。')

        mapping = {}
        for row in reader:
            class_id = int(row['class_id'])
            class_name = row['class_name']
            mapping[class_id] = class_name

    if not mapping:
        raise ValueError(f"CSV {csv_path} 中未找到任何类别映射。")

    return mapping


class LSNetModelLoader:
    """「守望-LSNet模型加载器」:加载 LSNet 画师风格分类模型,输出模型包供风格反推器使用。"""

    @classmethod
    def INPUT_TYPES(cls):
        base_dir = os.path.join(folder_paths.models_dir, 'lsnet')
        subfolders = []
        if os.path.exists(base_dir):
            subfolders = [f for f in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, f))]

        return {
            "required": {
                "模型文件夹": (subfolders, {"default": subfolders[0] if subfolders else ""}),
                "设备": (["cuda", "cpu"], {"default": "cuda"}),
            }
        }

    RETURN_TYPES = ("LSNET_MODEL",)
    RETURN_NAMES = ("模型",)
    FUNCTION = "load"
    CATEGORY = "守望🐢/模型"
    DESCRIPTION = "从 models/lsnet/<模型文件夹> 加载 LSNet 画师风格分类模型，模型类型自动从 config.json 读取，输出模型包供守望-LSNet风格反推器使用。"

    def load(self, 模型文件夹, 设备):
        base_dir = os.path.join(folder_paths.models_dir, 'lsnet')
        model_dir = os.path.join(base_dir, 模型文件夹)
        checkpoint_path = os.path.join(model_dir, "best_checkpoint.pth")
        csv_path = os.path.join(model_dir, "class_mapping.csv")

        if not os.path.exists(checkpoint_path):
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Class mapping CSV not found: {csv_path}")
        class_mapping = load_class_mapping(csv_path)
        state_dict = load_checkpoint_state(checkpoint_path)
        state_dict = normalize_state_dict_keys(state_dict)
        num_classes = resolve_num_classes(None, class_mapping, state_dict)
        feature_dim = resolve_feature_dim(None, state_dict)

        # 自动从config.json读取model类型
        config_path = os.path.join(model_dir, "config.json")
        model_type = 'lsnet_xl_artist'  # 默认值
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'model' in config and config['model'] in ['lsnet_t_artist', 'lsnet_s_artist', 'lsnet_b_artist', 'lsnet_l_artist', 'lsnet_xl_artist', 'lsnet_xl_artist_448']:
                        model_type = config['model']
                        print(f"Model type loaded from config: {model_type}")
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}")

        model = create_model(
            model_type,
            pretrained=False,
            num_classes=num_classes,
            feature_dim=feature_dim,
        )
        model.load_state_dict(state_dict, strict=False)
        model.to(设备)
        model.eval()

        # 根据模型配置动态设置输入大小
        input_size = 224  # 默认值
        if model_type in default_cfgs_artist:
            model_cfg = default_cfgs_artist[model_type]
            configured_input_size = model_cfg.get('input_size', (3, 224, 224))[1]  # 获取高度（假设正方形）
            input_size = configured_input_size
            print(f"Auto-setting input_size to {input_size} for model {model_type}")

        config = resolve_data_config({'input_size': (3, input_size, input_size)}, model=model)
        transform = create_transform(**config)
        model_bundle = {
            'model': model,
            'transform': transform,
            'class_mapping': class_mapping,
            'device': 设备
        }

        return (model_bundle,)


NODE_CLASS_MAPPINGS = {
    "ShouWangLSNetModelLoader": LSNetModelLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangLSNetModelLoader": "守望-LSNet模型加载器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
