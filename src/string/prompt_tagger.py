import csv
import io
import json
import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image
import torch

# ============ 模型目录与预处理常量 ============

# 插件根目录：当前文件在 <插件>/src/string/ 下，上三级即插件根目录
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tagger_dir() -> str:
    """模型目录：优先 ComfyUI 标准模型根目录（folder_paths.models_dir）下的 tagger，
    兼容任意安装位置；兜底相对插件路径（custom_nodes 上一级 models/tagger）"""
    try:
        from folder_paths import models_dir
        base = models_dir
    except Exception:
        base = os.path.normpath(os.path.join(PLUGIN_ROOT, "..", "..", "models"))
    return os.path.normpath(os.path.join(base, "tagger"))

# pixai 系列固定输入尺寸（Resize((448,448)) 直接拉伸）
INPUT_SIZE = 448

# selected_tags.csv 的 category 编号 → 类别名（wd-eva02-large-tagger-v3 实测：
# 9=rating 评分、0=general 常规、4=character 角色；未列出的编号归入 general）
CSV_CATEGORY_MAP = {
    0: "general",
    4: "character",
    9: "rating",
}

# LabelData 支持的类别（tag_mapping.json 类别名小写集合）
VALID_CATEGORIES = {
    "rating", "general", "artist", "character", "copyright", "meta", "quality", "model",
}


def process_tag(tag: str, replace_underscore: bool, escape_parentheses: bool) -> str:
    """处理单个标签：替换下划线、转义括号（保留 ComfyUI 权重格式 (内容:数值)）"""
    if not tag:
        return tag

    if replace_underscore:
        tag = tag.replace("_", " ")

    if escape_parentheses:
        # ComfyUI 权重格式（两段式 (内容:数值) 或三段式 (内容:数值:数值)），整串匹配则不转义
        weight_pattern = r'\([^:()]+:\d+(?:\.\d+)?(?::\d+(?:\.\d+)?)?\)$'
        if not re.match(weight_pattern, tag):
            # 仅转义未转义的括号，避免对已转义的 \( \) 造成双重转义
            tag = re.sub(r'(?<!\\)\(', r'\(', tag)
            tag = re.sub(r'(?<!\\)\)', r'\)', tag)

    return tag


def _model_folders() -> List[str]:
    """列出 models/tagger 目录下包含模型文件的文件夹名"""
    tagger_dir = _tagger_dir()
    if not os.path.isdir(tagger_dir):
        return []
    result = []
    for f in sorted(os.listdir(tagger_dir)):
        folder = os.path.join(tagger_dir, f)
        if not os.path.isdir(folder):
            continue
        has_model = any(
            os.path.exists(os.path.join(folder, n))
            for n in ("model.onnx", "model_optimized.onnx", "model_v0.9.pth")
        )
        # JTP 风格：任意 .safetensors + tags.json
        has_model = has_model or any(
            fn.endswith(".safetensors")
            for fn in os.listdir(folder)
        ) and os.path.exists(os.path.join(folder, "tags.json"))
        if has_model:
            result.append(f)
    return result


def _tagger_kind(model_dir: str) -> str:
    """判断文件夹内模型引擎类型：onnx / pth / jtp，无则返回空字符串"""
    if any(os.path.exists(os.path.join(model_dir, n)) for n in ("model.onnx", "model_optimized.onnx")):
        return "onnx"
    if os.path.exists(os.path.join(model_dir, "model_v0.9.pth")):
        return "pth"
    if any(f.endswith(".safetensors") for f in os.listdir(model_dir)):
        return "jtp"
    return ""


# --- 数据类和辅助功能 ---
@dataclass
class LabelData:
    names: list[str]
    rating: list[np.int64]
    general: list[np.int64]
    artist: list[np.int64]
    character: list[np.int64]
    copyright: list[np.int64]
    meta: list[np.int64]
    quality: list[np.int64]
    model: list[np.int64]


def pil_ensure_rgb(image: Image.Image) -> Image.Image:
    """RGBA/P 模式图片转 RGB（透明区域填充白色）"""
    if image.mode not in ["RGB", "RGBA"]:
        image = image.convert("RGBA") if "transparency" in image.info else image.convert("RGB")
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[3])
        image = background
    return image


def get_tags(probs, labels: LabelData, gen_threshold, char_threshold):
    """按类别阈值筛选标签（参考 WD14-Tagger：概率已含 sigmoid，直接比较）"""
    result = {"rating": [], "general": [], "character": [], "copyright": [], "artist": [], "meta": [], "quality": [], "model": []}

    def get_max(indices, category_name):
        if len(indices) > 0:
            valid = indices[indices < len(probs)]
            if len(valid) > 0:
                p = probs[valid]
                idx_local = np.argmax(p)
                idx_global = valid[idx_local]
                if idx_global < len(labels.names) and labels.names[idx_global] is not None:
                    result[category_name].append((labels.names[idx_global], float(p[idx_local])))

    get_max(labels.rating, "rating")
    get_max(labels.quality, "quality")

    category_map = {
        "general": (labels.general, gen_threshold),
        "character": (labels.character, char_threshold),
        "copyright": (labels.copyright, char_threshold),
        "artist": (labels.artist, char_threshold),
        "meta": (labels.meta, gen_threshold),
        "model": (labels.model, gen_threshold)
    }
    for category, (indices, threshold) in category_map.items():
        if len(indices) > 0:
            valid = indices[indices < len(probs)]
            if len(valid) > 0:
                p = probs[valid]
                for idx_local, idx_global in enumerate(valid):
                    if p[idx_local] >= threshold:
                        if idx_global < len(labels.names) and labels.names[idx_global] is not None:
                            result[category].append((labels.names[idx_global], float(p[idx_local])))

    for k in result:
        result[k] = sorted(result[k], key=lambda x: x[1], reverse=True)
    return result


_CJK_FONT_SET = False


def _setup_cjk_font():
    """注册系统中文字体（微软雅黑优先），避免图表中文显示为方块"""
    global _CJK_FONT_SET
    if _CJK_FONT_SET:
        return
    _CJK_FONT_SET = True
    import matplotlib
    import matplotlib.font_manager as fm
    matplotlib.use("Agg")  # 无显示环境（后端服务）安全绘图
    import matplotlib.pyplot as plt
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("msyh.ttc", "simhei.ttf"):
        path = os.path.join(windir, "Fonts", name)
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            plt.rcParams['font.family'] = fm.FontProperties(fname=path).get_name()
            plt.rcParams['axes.unicode_minus'] = False
            return


def visualize_predictions(predictions: Dict, threshold: float, switches: Dict, width_px=1000, height_px=1200):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    _setup_cjk_font()
    # 过滤不想要的元数据标签
    filtered_meta = []
    excluded_meta_patterns = ['id', 'commentary', 'request', 'mismatch']
    for tag, prob in predictions.get("meta", []):
        if not any(pattern in tag.lower() for pattern in excluded_meta_patterns):
            filtered_meta.append((tag, prob))
    predictions["meta"] = filtered_meta

    dpi = 100
    width_in = width_px / dpi
    height_in = height_px / dpi
    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    ax_tags = fig.add_subplot(1, 1, 1)

    all_tags, all_probs, all_colors = [], [], []
    color_map = {
        'rating': 'red', 'character': 'blue', 'copyright': 'purple',
        'artist': 'orange', 'general': 'green', 'meta': 'gray', 'quality': 'yellow', 'model': 'cyan'
    }

    for cat, prefix, color in [
        ('rating', 'R', color_map['rating']), ('quality', 'Q', color_map['quality']),
        ('character', 'C', color_map['character']), ('copyright', '©', color_map['copyright']),
        ('artist', 'A', color_map['artist']), ('general', 'G', color_map['general']),
        ('meta', 'M', color_map['meta']), ('model', 'M', color_map['model'])
    ]:
        if not switches.get(cat, True):
            continue  # 根据开关过滤
        for tag, prob in predictions.get(cat, []):
            all_tags.append(f"[{prefix}] {tag.replace('_', ' ')}")
            all_probs.append(prob)
            all_colors.append(color)

    if not all_tags:
        ax_tags.text(0.5, 0.5, "No tags found above threshold or all categories disabled", ha='center', va='center')
        ax_tags.axis('off')
    else:
        sorted_indices = sorted(range(len(all_probs)), key=lambda i: all_probs[i])
        all_tags = [all_tags[i] for i in sorted_indices]
        all_probs = [all_probs[i] for i in sorted_indices]
        all_colors = [all_colors[i] for i in sorted_indices]

        y_positions = np.arange(len(all_tags))
        ax_tags.barh(y_positions, all_probs, color=all_colors)
        ax_tags.set_yticks(y_positions)
        ax_tags.set_yticklabels(all_tags)

        fontsize = 10 if len(all_tags) <= 40 else 8
        for lbl in ax_tags.get_yticklabels():
            lbl.set_fontsize(fontsize)

        for i, prob in enumerate(all_probs):
            ax_tags.text(prob + 0.01, i, f"{prob:.3f}", va='center', fontsize=fontsize)

        ax_tags.set_xlim(0, 1.1)
        ax_tags.set_title(f"预测可视化 (阈值 ~{threshold:.2f})")

        legend_elements = [Patch(facecolor=c, label=cat.capitalize()) for cat, c in color_map.items() if any(t.startswith(f"[{cat[0].upper() if cat != 'copyright' else '©'}]") for t in all_tags)]
        if legend_elements:
            ax_tags.legend(handles=legend_elements, loc='lower right', fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf)


# --- 标签文件解析 ---

def _build_label_data(label_names, category_indices: Dict[str, List[int]]) -> LabelData:
    """根据标签名列表与类别索引构建 LabelData"""
    mapping = {"Rating": [], "General": [], "Artist": [], "Character": [], "Copyright": [], "Meta": [], "Quality": [], "Model": []}
    for cat, indices in category_indices.items():
        key = cat.capitalize()
        if key in mapping:
            mapping[key].extend(indices)
    return LabelData(
        names=label_names,
        rating=np.array(mapping["Rating"], dtype=np.int64),
        general=np.array(mapping["General"], dtype=np.int64),
        artist=np.array(mapping["Artist"], dtype=np.int64),
        character=np.array(mapping["Character"], dtype=np.int64),
        copyright=np.array(mapping["Copyright"], dtype=np.int64),
        meta=np.array(mapping["Meta"], dtype=np.int64),
        quality=np.array(mapping["Quality"], dtype=np.int64),
        model=np.array(mapping["Model"], dtype=np.int64),
    )


def _load_csv_tags(csv_path: str) -> LabelData:
    """解析 WD14 风格标签文件 selected_tags.csv（列：tag_id,name,category,count）。

    注意：标签按 CSV 行序排列，行序即模型输出索引顺序（与 ComfyUI-WD14-Tagger 一致），
    tag_id 列仅作参考，不能作为输出索引。
    """
    names, categories = [], []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # 表头
        for row in reader:
            if len(row) < 3:
                continue
            try:
                names.append(row[1])
                categories.append(int(row[2]))
            except ValueError:
                continue

    if not names:
        raise ValueError(f"标签文件为空或格式错误: {csv_path}")

    category_indices: Dict[str, List[int]] = {}
    for idx, category in enumerate(categories):
        cat = CSV_CATEGORY_MAP.get(category, "general")
        category_indices.setdefault(cat, []).append(idx)

    return _build_label_data(names, category_indices)


def _load_pixai_tags(json_path: str) -> LabelData:
    """解析 pixai 官方标签文件 tags_v0.9_13k.json（tag_map + tag_split）。

    标签索引连续：0 ~ gen_tag_count-1 为常规(general)，其后为角色(character)。
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tag_map = data.get("tag_map")
    if not tag_map:
        raise ValueError(f"标签文件缺少 tag_map 字段: {json_path}")
    split = data.get("tag_split", {})
    gen_count = int(split.get("gen_tag_count", 0))

    label_names = [None] * len(tag_map)
    for tag, idx in tag_map.items():
        idx = int(idx)
        if 0 <= idx < len(label_names):
            label_names[idx] = tag

    category_indices = {
        "general": list(range(min(gen_count, len(label_names)))),
        "character": list(range(min(gen_count, len(label_names)), len(label_names))),
    }
    return _build_label_data(label_names, category_indices)


def _load_json_tags(json_path: str) -> LabelData:
    """解析 tag_mapping.json（deepghs/pixai onnx 风格：idx_to_tag + tag_to_category）"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if "idx_to_tag" in data:
        idx_to_tag = {int(k): v for k, v in data["idx_to_tag"].items()}
        tag_to_category = data["tag_to_category"]
    else:
        data_int = {int(k): v for k, v in data.items()}
        idx_to_tag = {idx: d['tag'] for idx, d in data_int.items()}
        tag_to_category = {d['tag']: d['category'] for d in data_int.values()}

    label_names = [None] * (max(idx_to_tag.keys()) + 1)
    category_indices: Dict[str, List[int]] = {}
    for idx, tag in idx_to_tag.items():
        label_names[idx] = tag
        cat = tag_to_category.get(tag, 'Unknown')
        # 兼容大小写（如 General/general），未知类别归入 general
        if cat.lower() not in VALID_CATEGORIES:
            cat = "general"
        category_indices.setdefault(cat, []).append(int(idx))

    return _build_label_data(label_names, category_indices)


def _resolve_label_data(model_dir: str, name: str) -> Tuple[LabelData, str]:
    """按优先级解析标签文件，返回 (LabelData, 标签格式文件名)"""
    for candidate, loader in (
        ("selected_tags.csv", _load_csv_tags),
        ("tags_v0.9_13k.json", _load_pixai_tags),
        ("tag_mapping.json", _load_json_tags),
    ):
        path = os.path.join(model_dir, candidate)
        if os.path.exists(path):
            return loader(path), candidate
    raise FileNotFoundError(
        f"模型文件夹「{name}」中缺少标签文件（需要 selected_tags.csv / tags_v0.9_13k.json / tag_mapping.json 之一）"
    )


# --- 预处理（对齐官方参考实现） ---

def _preprocess_wd14(image: Image.Image, height: int) -> np.ndarray:
    """WD14 参考（ComfyUI-WD14-Tagger）：等比缩放 + 白色正方形填充 + RGB→BGR。

    不归一化：SmilingWolf 的 onnx 图内含归一化层，直接喂 0-255 值；
    布局 NHWC [1, H, W, 3]，与 onnx 输入 shape 一致。
    """
    ratio = float(height) / max(image.size)
    new_size = tuple([int(x * ratio) for x in image.size])
    image = image.resize(new_size, Image.LANCZOS)
    square = Image.new("RGB", (height, height), (255, 255, 255))
    square.paste(image, ((height - new_size[0]) // 2, (height - new_size[1]) // 2))

    arr = np.array(square).astype(np.float32)
    arr = arr[:, :, ::-1]  # RGB -> BGR
    return np.expand_dims(arr, 0)


def _preprocess_pixai(image: Image.Image) -> torch.Tensor:
    """pixai 官方参考（handler.py）：直接拉伸 448×448 + ToTensor + Normalize(0.5)。

    归一化到 [-1, 1]，布局 NCHW [1, 3, 448, 448]。
    """
    image = image.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR)
    arr = np.array(image, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)
    arr = (arr - 0.5) / 0.5
    return torch.from_numpy(arr.astype(np.float32)).unsqueeze(0)


def _preprocess_jtp(image: Image.Image) -> torch.Tensor:
    """FD-Tagger 官方参考（image_manager）：等比缩放≤384 + RGBA 灰底(0.5)合成 + Normalize(0.5)。

    归一化到 [-1, 1]，布局 NCHW [1, 3, 384, 384]，中心裁剪。
    """
    image = image.convert("RGBA")
    w, h = image.size
    scale = min(384.0 / h, 384.0 / w)  # Fit(grow=True)：等比缩放至不超过 384，小图放大
    if scale != 1.0:
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    arr = np.array(image).astype(np.float32) / 255.0  # [H,W,4] 0-1
    alpha = arr[..., 3:4]
    rgb = arr[..., :3] * alpha + 0.5 * (1.0 - alpha)  # CompositeAlpha：透明区域合成 0.5 灰底
    hh, ww = rgb.shape[:2]
    top, left = max(0, (hh - 384) // 2), max(0, (ww - 384) // 2)  # CenterCrop(384,384)
    crop = rgb[top:top + 384, left:left + 384]
    if crop.shape[0] < 384 or crop.shape[1] < 384:  # 超细长图：右下补零（对齐官方 pad 行为）
        crop = np.pad(crop, ((0, 384 - crop.shape[0]), (0, 384 - crop.shape[1]), (0, 0)), mode="constant")
    arr = (crop - 0.5) / 0.5  # Normalize(mean=0.5, std=0.5) → [-1,1]
    return torch.from_numpy(arr.transpose(2, 0, 1).copy()).unsqueeze(0)


# CLIP 系模型（cl_tagger 等）归一化参数（OpenAI CLIP 参考值）
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def _preprocess_clip(image: Image.Image, size: int = 448) -> np.ndarray:
    """CLIP 系反推模型（cl_tagger 等）：等比缩放短边 + 中心裁剪 + CLIP mean/std 归一化。

    对齐 OpenAI CLIP 参考预处理（Resize 短边 + CenterCrop + normalize），
    布局 NCHW [1, 3, size, size]；归一化后值域约 [-2.5, 2.5]。
    """
    w, h = image.size
    scale = float(size) / min(w, h)  # Fit：短边对齐 size
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    image = image.resize(new_size, Image.BICUBIC)
    left = (new_size[0] - size) // 2
    top = (new_size[1] - size) // 2
    image = image.crop((left, top, left + size, top + size))
    arr = np.array(image).astype(np.float32) / 255.0
    arr = (arr - CLIP_MEAN) / CLIP_STD
    return np.expand_dims(arr.transpose(2, 0, 1), 0)


# --- 反推器 ---

class TaggingHead(torch.nn.Module):
    """pixai 官方分类头（键名 head.*，与官方导出权重一致）"""

    def __init__(self, input_dim, num_classes):
        super().__init__()
        self.head = torch.nn.Sequential(torch.nn.Linear(input_dim, num_classes))

    def forward(self, x):
        return torch.sigmoid(self.head(x))


class OnnxTagger:
    """ONNX 反推器：WD14 风格（model.onnx + selected_tags.csv）与 pixai/deepghs onnx 兼容"""

    def __init__(self, name, model_dir):
        self.name = name
        self.model_dir = model_dir
        self.model_path = None
        self.tags = None
        self.model = None
        self.wd14_style = False  # 历史字段：True=WD14 预处理；现由 self.preprocess 统一管理
        self.input_height = INPUT_SIZE
        self.nhwc = False

    def load(self):
        from onnxruntime import InferenceSession

        # 模型文件：优先 model.onnx，其次 model_optimized.onnx
        for candidate in ("model.onnx", "model_optimized.onnx"):
            path = os.path.join(self.model_dir, candidate)
            if os.path.exists(path):
                self.model_path = path
                break
        if self.model_path is None:
            raise FileNotFoundError(f"模型文件夹「{self.name}」中缺少 model.onnx 或 model_optimized.onnx")

        # 标签文件（其格式决定预处理方式）
        self.tags, tag_format = _resolve_label_data(self.model_dir, self.name)

        # 设备：优先 CUDA，失败自动回退 CPU
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        try:
            self.model = InferenceSession(str(self.model_path), providers=providers)
        except Exception:
            self.model = InferenceSession(str(self.model_path), providers=['CPUExecutionProvider'])

        # 读取输入规格（WD14 onnx 为 NHWC float32，高度 448）
        inp = self.model.get_inputs()[0]
        shape = list(inp.shape)
        self.nhwc = (len(shape) == 4 and shape[-1] == 3)
        if self.nhwc:
            self.input_height = int(shape[1]) if isinstance(shape[1], int) else INPUT_SIZE
        else:
            # NCHW：高度取 shape[2]（如 pixai [1,3,448,448]、cl_tagger [1,3,H,W]）
            self.input_height = int(shape[2]) if isinstance(shape[2], int) else INPUT_SIZE

        # 预处理方式由「标签文件格式 + 输入尺寸」共同决定：
        # - selected_tags.csv（WD14）→ WD14 等比白底 0-255 BGR
        # - 动态尺寸输入（cl_tagger 等 CLIP 系）→ 等比短边 + 中心裁剪 + CLIP mean/std
        # - 固定尺寸输入（pixai/deepghs onnx）→ 拉伸 + [-1,1]
        if tag_format == "selected_tags.csv":
            self.preprocess = "wd14"
        elif any(not isinstance(d, int) for d in shape[2:]):
            self.preprocess = "clip"
        else:
            self.preprocess = "pixai"

    def interrogate(self, image: Image, gen_threshold, char_threshold):
        if self.model is None:
            self.load()
        image = pil_ensure_rgb(image)

        if self.preprocess == "wd14":
            arr = _preprocess_wd14(image, self.input_height)  # NHWC
            if not self.nhwc:
                arr = arr.transpose(0, 3, 1, 2)  # 转 NCHW
        elif self.preprocess == "clip":
            arr = _preprocess_clip(image, self.input_height)  # NCHW
            if self.nhwc:
                arr = arr.transpose(0, 2, 3, 1)  # 转 NHWC
        else:
            arr = _preprocess_pixai(image).numpy()  # NCHW
            if self.nhwc:
                arr = arr.transpose(0, 2, 3, 1)  # 转 NHWC

        outputs = self.model.run([self.model.get_outputs()[0].name], {self.model.get_inputs()[0].name: arr})[0]
        probs = outputs[0]
        # 部分模型（如 cl_tagger_1_02）输出未激活的 logits：超出概率范围 [0,1] 时应用 sigmoid
        if float(probs.max()) > 1.0:
            probs = 1.0 / (1.0 + np.exp(-probs))
        return get_tags(probs, self.tags, gen_threshold, char_threshold)


class PthTagger:
    """pixai 官方 PyTorch 反推器（model_v0.9.pth + tags_v0.9_13k.json）"""

    def __init__(self, name, model_dir):
        self.name = name
        self.model_dir = model_dir
        self.model_path = None
        self.tags = None
        self.model = None
        self.device = "cpu"

    def load(self):
        # 模型文件
        pth_path = os.path.join(self.model_dir, "model_v0.9.pth")
        if not os.path.exists(pth_path):
            raise FileNotFoundError(f"模型文件夹「{self.name}」中缺少 model_v0.9.pth")
        self.model_path = pth_path

        # 标签文件（pixai 官方 tags_v0.9_13k.json，兼容其他格式）
        self.tags, _ = _resolve_label_data(self.model_dir, self.name)

        # timm 内置架构，离线构建（无需联网下载权重）
        import timm
        num_classes = len(self.tags.names)
        encoder = timm.create_model("eva02_large_patch14_448", pretrained=False)
        encoder.reset_classifier(0)
        model = torch.nn.Sequential(encoder, TaggingHead(1024, num_classes))

        state = torch.load(self.model_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = model.to(self.device).eval()

    def interrogate(self, image: Image, gen_threshold, char_threshold):
        if self.model is None:
            self.load()
        image = pil_ensure_rgb(image)
        tensor = _preprocess_pixai(image).to(self.device)
        with torch.inference_mode():
            probs = self.model(tensor)[0].cpu().numpy()
        return get_tags(probs, self.tags, gen_threshold, char_threshold)


class V2GatedHead(torch.nn.Module):
    """FD-Tagger version 2 门控分类头：sigmoid(前半) × sigmoid(后半)（权重键名 head.linear.*）"""

    def __init__(self, num_features, num_classes):
        super().__init__()
        self.num_classes = num_classes
        self.linear = torch.nn.Linear(num_features, num_classes * 2)
        self.act = torch.nn.Sigmoid()
        self.gate = torch.nn.Sigmoid()

    def forward(self, x):
        x = self.linear(x)
        return self.act(x[:, :self.num_classes]) * self.gate(x[:, self.num_classes:])


class JtpTagger:
    """FD-Tagger 风格（JTP_PILOT2 等）：.safetensors + tags.json，e621 标签无类别。

    v1 头为普通 Linear（输出需 sigmoid）；v2 头为 V2GatedHead（门控乘积即概率，无需再激活）。
    """

    INPUT_SIZE = 384

    def __init__(self, name, model_dir):
        self.name = name
        self.model_dir = model_dir
        self.model_path = None
        self.tags = None
        self.model = None
        self.device = "cpu"
        self.dtype = torch.float32

    def load(self):
        import timm
        import safetensors.torch
        from safetensors import safe_open

        # 模型文件：文件夹内任意 .safetensors
        st_files = [f for f in os.listdir(self.model_dir) if f.endswith(".safetensors")]
        if not st_files:
            raise FileNotFoundError(f"模型文件夹「{self.name}」中缺少 .safetensors 模型文件")
        self.model_path = os.path.join(self.model_dir, st_files[0])

        # 标签文件 tags.json：dict {标签: 输出索引}，e621 标签无类别，全部归入 general
        tags_path = os.path.join(self.model_dir, "tags.json")
        if not os.path.exists(tags_path):
            raise FileNotFoundError(f"模型文件夹「{self.name}」中缺少 tags.json 标签文件")
        with open(tags_path, "r", encoding="utf-8") as f:
            tags_data = json.load(f)
        num_classes = len(tags_data)
        label_names = [None] * num_classes
        for tag, idx in tags_data.items():
            idx = int(idx)
            if 0 <= idx < num_classes:
                label_names[idx] = tag
        self.tags = _build_label_data(label_names, {"general": list(range(num_classes))})

        # timm 内置 SigLIP 架构，离线构建；按权重键名区分 v1/v2 头
        encoder = timm.create_model("vit_so400m_patch14_siglip_384.webli", pretrained=False, num_classes=num_classes)
        with safe_open(self.model_path, framework="pt") as f:
            keys = set(f.keys())
            if "head.linear.weight" in keys:  # v2 门控头（linear 输出 num_classes*2）
                head_shape = f.get_slice("head.linear.weight").get_shape()
                encoder.head = V2GatedHead(head_shape[1], num_classes)
            elif "head.weight" not in keys:  # v1 普通 Linear（timm 默认 head），缺 head 则报错
                raise RuntimeError(f"模型文件「{os.path.basename(self.model_path)}」中未找到分类头权重")
        safetensors.torch.load_model(encoder, self.model_path)

        # 设备：CUDA 用 fp16（对齐官方），CPU 用 fp32
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = encoder.to(self.device, dtype=self.dtype).eval()

    def interrogate(self, image: Image, gen_threshold, char_threshold):
        if self.model is None:
            self.load()
        # 不走 pil_ensure_rgb：JTP 需要保留透明通道做灰底合成
        tensor = _preprocess_jtp(image).to(self.device, dtype=self.dtype)
        with torch.inference_mode():
            probs = self.model(tensor)[0].float().cpu().numpy()
        return get_tags(probs, self.tags, gen_threshold, char_threshold)


def _create_tagger(name: str, model_dir: str):
    """按文件夹内模型文件类型创建对应反推器"""
    kind = _tagger_kind(model_dir)
    if kind == "onnx":
        return OnnxTagger(name, model_dir)
    if kind == "pth":
        return PthTagger(name, model_dir)
    if kind == "jtp":
        return JtpTagger(name, model_dir)
    raise RuntimeError(
        f"模型文件夹「{name}」中未找到模型文件（需要 model.onnx / model_optimized.onnx / "
        f"model_v0.9.pth / *.safetensors）"
    )


# --- 节点定义 ---

class ShouWangVizTaggerNode:
    def __init__(self):
        self.interrogators = {}

    @classmethod
    def INPUT_TYPES(cls):
        folders = _model_folders()
        if not folders:
            raise RuntimeError(
                f"未找到任何反推模型！请将模型文件夹放入 models/tagger 目录（如 "
                f"models/tagger/wd-eva02-large-tagger-v3/、models/tagger/pixai-tagger-v0.9/），"
                f"每个文件夹需包含模型文件（model.onnx / model_v0.9.pth / *.safetensors）和标签文件"
            )
        return {
            "required": {
                "模型名称": (folders,),
                "种子模式": (["随机", "固定"], {"default": "随机"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 999999999999999}),  # 15 位随机种子上限（与前端 JS 生成范围一致）
                "常规阈值": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05}),
                "角色阈值": ("FLOAT", {"default": 0.85, "min": 0.0, "max": 1.0, "step": 0.05}),
                "可视化宽度": ("INT", {"default": 800, "min": 400, "max": 3000, "step": 50}),
                "可视化高度": ("INT", {"default": 1400, "min": 600, "max": 5000, "step": 50}),
                "角色开关": ("BOOLEAN", {"default": True}),
                "常规开关": ("BOOLEAN", {"default": True}),
                "版权开关": ("BOOLEAN", {"default": False}),
                "替换下划线": ("BOOLEAN", {"default": True}),
                "转义括号": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "图片": ("IMAGE",),
                # 批量打标：接收「守望-Tagger批量反推器」节点的文件夹配置；连接后按批量模式执行（无需图片）
                "批量打标": ("TAGGER_BATCH",),
            }
        }

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("提示词", "可视化图表")
    FUNCTION = "generate"
    CATEGORY = "守望🐢/提示词"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """控制节点是否重新执行（返回值纳入缓存签名）：
        - 批量模式：每次执行（文件夹内容可能变化）
        - 随机：每次执行（每次生成新随机种子）
        - 固定：种子与上次一致 → 跳过执行；变化 → 执行
        """
        if kwargs.get("批量打标") is not None:
            return random.random()
        if kwargs.get("种子模式") == "随机":
            return random.random()
        return kwargs.get("种子", 0)

    # generate 形参：全参数静态声明（前端按模型类型显隐类别参数），默认值 + **kwargs 兼容历史工作流
    def generate(self, 图片=None, 批量打标=None, 模型名称=None, 种子模式="随机", 种子=0,
                 常规阈值=0.35, 角色阈值=0.85, 可视化宽度=800, 可视化高度=1400,
                 角色开关=True, 常规开关=True, 版权开关=False, 替换下划线=True, 转义括号=True, **kwargs):
        # 批量模式：连接了「批量打标」配置 → 对整个文件夹批量反推并保存 Tag 文件
        if 批量打标 is not None:
            return self._batch_generate(批量打标, 模型名称, 常规阈值, 角色阈值, 可视化宽度, 可视化高度, 替换下划线, 转义括号)
        if 图片 is None:
            raise ValueError("请连接「图片」（单图反推）或「批量打标」（文件夹批量打标）输入")
        if 模型名称 is None:
            raise ValueError("缺少「模型名称」参数")

        # 图片张量转PIL
        i = 255. * 图片.cpu().numpy().squeeze()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

        # 执行标签预测
        tagger = self._get_tagger(模型名称)
        preds = tagger.interrogate(img, 常规阈值, 角色阈值)

        # 组装标签
        switches = self._build_switches(角色开关, 常规开关, 版权开关)
        tags = self._assemble_tags(preds, switches, 替换下划线, 转义括号)

        # 种子模式：随机 → 使用本次输入的 15 位随机种子打乱标签顺序；固定 → 保持按概率降序
        if 种子模式 == "随机":
            rng = random.Random(种子)
            rng.shuffle(tags)

        # 生成可视化图
        viz_img = visualize_predictions(preds, 常规阈值, switches, 可视化宽度, 可视化高度)
        viz_tensor = torch.from_numpy(np.array(viz_img).astype(np.float32) / 255.0).unsqueeze(0)

        return (", ".join(tags), viz_tensor)

    def _get_tagger(self, 模型名称):
        """按模型名加载/获取反推器（缓存）"""
        if 模型名称 not in self.interrogators:
            model_dir = os.path.join(_tagger_dir(), 模型名称)
            if not os.path.isdir(model_dir):
                raise RuntimeError(
                    f"未找到模型文件夹「{模型名称}」，请确认其位于 models/tagger 目录"
                )
            self.interrogators[模型名称] = _create_tagger(模型名称, model_dir)
        return self.interrogators[模型名称]

    def _build_switches(self, 角色开关, 常规开关, 版权开关):
        """开关映射：仅角色/常规/版权保留开关；其余类别（评分/艺术家/元数据/质量/模型）固定不输出"""
        return {
            "rating": False,
            "general": 常规开关,
            "artist": False,
            "character": 角色开关,
            "copyright": 版权开关,
            "meta": False,
            "quality": False,
            "model": False,
        }

    def _assemble_tags(self, preds, switches, 替换下划线, 转义括号):
        """按开关与格式化选项组装标签列表（不含种子打乱）"""
        tags = []
        excluded = ['id', 'commentary', 'request', 'mismatch']
        for cat in ["rating", "quality", "artist", "character", "copyright", "general", "meta", "model"]:
            if not switches.get(cat, True):
                continue
            for tag, prob in preds.get(cat, []):
                if cat == "meta" and any(p in tag.lower() for p in excluded):
                    continue
                tags.append(process_tag(tag, 替换下划线, 转义括号))
        return tags

    def _batch_generate(self, config, 模型名称, 常规阈值, 角色阈值, 可视化宽度, 可视化高度,
                        替换下划线, 转义括号):
        """批量模式：扫描文件夹内图片 → 模型反推 → 保存 Tag 文件（附加提示词放最前，不打乱顺序）"""
        folder = str(config.get("folder", "")).strip()
        fmt = str(config.get("format", "txt")).strip() or "txt"
        extra_prompt = str(config.get("extra_prompt", ""))
        recursive = bool(config.get("recursive", False))
        exists_action = str(config.get("exists", "忽略"))
        if 模型名称 is None:
            raise ValueError("缺少「模型名称」参数")
        if not os.path.isdir(folder):
            raise ValueError(f"批量打标：文件夹不存在：{folder}")

        # 扫描图片文件（png/jpg/jpeg/webp/bmp）
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        files = []
        if recursive:
            for root, _dirs, fnames in os.walk(folder):
                for fn in sorted(fnames):
                    if fn.lower().endswith(exts):
                        files.append(os.path.join(root, fn))
        else:
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith(exts):
                    files.append(os.path.join(folder, fn))
        if not files:
            raise ValueError(f"批量打标：文件夹中未找到图片文件（{', '.join(exts)}）：{folder}")

        # 附加提示词（逗号分隔，放最前）
        extra_tags = [t.strip() for t in extra_prompt.split(",") if t.strip()]

        tagger = self._get_tagger(模型名称)
        switches = self._build_switches(True, True, False)
        summary = []
        ok = skip = fail = 0
        for path in files:
            base = os.path.basename(path)
            try:
                img = Image.open(path)
                img.load()
                preds = tagger.interrogate(img, 常规阈值, 角色阈值)
                tags = self._assemble_tags(preds, switches, 替换下划线, 转义括号)
                if extra_tags:
                    tags = extra_tags + tags
                text = ", ".join(tags)
                out_path = os.path.splitext(path)[0] + "." + fmt
                existed = os.path.exists(out_path)
                if existed and exists_action == "忽略":
                    skip += 1
                    summary.append((base, "跳过·已存在", None))
                    continue
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
                ok += 1
                summary.append((base, "覆盖" if existed else "写入", tags[:3]))
            except Exception as e:
                fail += 1
                summary.append((base, "失败", str(e)))

        # 汇总文本与结果图
        info = (
            f"批量打标完成：共 {len(files)} 张 | 成功 {ok} | 跳过 {skip}（已存在·忽略）| 失败 {fail}\n"
            f"保存目录：{folder}\n"
            f"打标格式：.{fmt} | 递归搜索：{'开' if recursive else '关'} | 已存在处理：{exists_action}"
        )
        viz_tensor = self._batch_viz(summary, 可视化宽度, 可视化高度)
        return (info, viz_tensor)

    def _batch_viz(self, summary, width_px, height_px):
        """批量结果汇总图：每张图一行（文件名 + 状态 + top3 标签）"""
        import matplotlib.pyplot as plt
        _setup_cjk_font()
        dpi = 100
        fig = plt.figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
        ax = fig.add_subplot(1, 1, 1)
        ax.axis('off')
        lines = []
        for i, (base, status, detail) in enumerate(summary, 1):
            if detail is None:
                lines.append(f"{i:3d}. {base}  [{status}]")
            elif isinstance(detail, list):
                top = ", ".join(detail[:3]) if detail else "(无标签)"
                lines.append(f"{i:3d}. {base}  [{status}]  {top}")
            else:
                lines.append(f"{i:3d}. {base}  [{status}]  {detail}")
        fontsize = 10 if len(lines) <= 40 else (8 if len(lines) <= 100 else 6)
        ax.text(0.01, 0.99, "\n".join(lines), transform=ax.transAxes, va='top', ha='left',
                fontsize=fontsize)
        ax.set_title(f"批量打标结果（共 {len(lines)} 张）")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        viz_img = Image.open(buf)
        return torch.from_numpy(np.array(viz_img).astype(np.float32) / 255.0).unsqueeze(0)


NODE_CLASS_MAPPINGS = {
    "ShouWangVizTagger": ShouWangVizTaggerNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangVizTagger": "守望-Tagger反推器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']