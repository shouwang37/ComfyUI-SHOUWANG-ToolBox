# 守望-Tagger反推器🐢 说明文档

> 对应代码：[prompt_tagger.py](./prompt_tagger.py) ｜ 节点名称：`守望-Tagger反推器🐢` ｜ 节点类别：`守望🐢/提示词`

## 一、节点概述

对输入图片进行多标签反推，输出可直接使用的提示词文本与预测可视化图表。

- **输出 1「提示词」**：逗号分隔的标签字符串（可接提示词输入类节点）
- **输出 2「可视化图表」**：各标签置信度的横向条形图（IMAGE）

## 二、界面参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 模型名称 | 下拉框 | - | 按 `models/tagger` 下的文件夹名列出，自动识别；**切换模型时二级参数按模型能力动态刷新** |
| 图片 | IMAGE | - | 单图模式：输入单张图像反推（可选输入） |
| 批量打标 | TAGGER_BATCH | - | **批量模式**：连接「守望-Tagger批量反推器🐢」节点的输出后，对整个文件夹的图片批量反推并保存 Tag 文件（可选输入，与图片二选一） |
| 种子模式 | 下拉框 | 随机 | 随机 = 每次运行生成新 15 位随机种子并打乱顺序；固定 = 按置信度降序，种子未变化时跳过执行 |
| 种子 | INT | 0 | 随机模式下显示每次生成的 15 位随机数；固定模式下用于判断是否跳过执行 |
| 常规阈值 | FLOAT | 0.35 | 常规标签的置信度门槛 |
| 角色阈值 | FLOAT | 0.85 | 角色标签的置信度门槛（仅类别模型显示） |
| 可视化宽度 / 高度 | INT | 800 / 1400 | 输出图表尺寸 |
| 角色开关 / 常规开关 / 版权开关 | BOOLEAN | 开/开/关 | 各类别输出开关（仅类别模型显示；评分/艺术家/元数据/质量/模型类别无开关，固定不输出） |
| 替换下划线 | BOOLEAN | 开 | 标签中的 `_` 替换为空格 |
| 转义括号 | BOOLEAN | 开 | 标签中的 `(` `)` 转义为 `\(` `\)`，避免误触发权重语法 |

> **动态参数**：JTP（FD-Tagger 系）模型的标签无角色/常规等类别之分，选择该类模型时自动隐藏「角色阈值」与 3 个类别开关（角色/常规/版权）；选择 WD14 / pixai 类别模型时全部参数恢复显示。

> **批量模式**：连接「守望-Tagger批量反推器🐢」节点后，无需连接图片即可对整个文件夹批量反推，按「图片名.txt」保存（详见下方第八节）。

## 三、支持的模型

| 模型 | 推荐文件夹名 | 需要的文件 | 来源 |
| --- | --- | --- | --- |
| WD EVA02-Large Tagger v3 | `wd-eva02-large-tagger-v3` | `model.onnx` + `selected_tags.csv` | [SmilingWolf/wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| PixAI Tagger v0.9（官方 PyTorch） | `pixai-tagger-v0.9` | `model_v0.9.pth` + `tags_v0.9_13k.json`（可加 `char_ip_map.json`） | [pixai-labs/pixai-tagger-v0.9](https://huggingface.co/pixai-labs/pixai-tagger-v0.9) |
| PixAI Tagger v0.9（ONNX 兼容） | `pixai-tagger-v0.9-onnx` | `model.onnx` + `tag_mapping.json` | [deepghs/pixai-tagger-v0.9-onnx](https://huggingface.co/deepghs/pixai-tagger-v0.9-onnx) |
| JTP PILOT2（FD-Tagger，e621 风格） | `JTP_PILOT2` | `*.safetensors` + `tags.json` | [RedRocket/JointTaggerProject](https://huggingface.co/RedRocket/JointTaggerProject) |

> 模型文件夹只需放进 `models/tagger` 目录即会自动出现在「模型名称」下拉框中，无需改代码。

## 四、模型放置方法

模型统一放在 **ComfyUI 全局 models 目录下的 tagger 文件夹**（唯一位置，即 `../models/tagger`）：

```
ComfyUI/models/tagger/                  ← 文件夹名 = 下拉框显示名
├── wd-eva02-large-tagger-v3/
│   ├── model.onnx                      ← WD14 模型权重
│   └── selected_tags.csv               ← 标签文件（列：tag_id,name,category,count）
├── pixai-tagger-v0.9/
│   ├── model_v0.9.pth                  ← pixai 官方 PyTorch 权重（约 1.2GB）
│   ├── tags_v0.9_13k.json              ← pixai 标签文件（tag_map + tag_split，13461 个标签）
│   └── char_ip_map.json                ← 可选，角色 IP 关联表（本节点暂不输出 IP 标签）
└── JTP_PILOT2/
    ├── JTP_PILOT2-e3-vit_so400m_patch14_siglip_384.safetensors  ← JTP 权重（约 1.7GB）
    └── tags.json                       ← e621 标签文件（dict：标签→索引，9083 个）
```

要求：

- 每个文件夹必须同时包含**模型文件**和**标签文件**，缺失时报错
- 模型文件四选一：`model.onnx`（优先）/ `model_optimized.onnx` / `model_v0.9.pth` / `*.safetensors`
- 标签文件四选一（决定预处理方式）：`selected_tags.csv`（WD14 式）/ `tags_v0.9_13k.json`（pixai 式）/ `tag_mapping.json`（deepghs 兼容）/ `tags.json`（JTP 式，配合 safetensors）
- 若放置位置为空或不存在，节点加载时直接报错并提示放置路径

## 五、工作原理

### 1. 标签分类（类别映射）

| 模型 | 类别划分 |
| --- | --- |
| WD14（selected_tags.csv） | 按 CSV 的 category 列：`9`=评分（4 个）、`0`=常规、`4`=角色；未列出的编号归入常规 |
| pixai（tags_v0.9_13k.json） | 按 `tag_split` 切分：前 `gen_tag_count`（9740）为常规，其余（3721）为角色 |
| deepghs（tag_mapping.json） | 按 `tag_to_category` 字段映射，兼容大小写，未知类别归入常规 |
| JTP（tags.json） | e621 标签**无类别之分**，全部归入常规（界面自动隐藏角色阈值与类别开关） |

- 评分/质量/艺术家/元数据/模型类别**固定不输出**（无开关），仅角色/常规/版权可开关控制
- 角色与版权共用角色阈值，常规按常规阈值过滤

### 2. 预处理（对齐官方参考实现，两套并存）

| 模型类型 | 预处理 | 依据 |
| --- | --- | --- |
| WD14 ONNX | 等比缩放 + 白色正方形填充 + **RGB→BGR**，直接喂 **0-255** 原值（onnx 图内含归一化层），输入布局 **NHWC** | [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) |
| PixAI（pth / onnx 兼容） | 直接拉伸 **448×448** + 归一化到 **[-1, 1]**（mean=std=0.5），输入布局 **NCHW** | [pixai-tagger-v0.9/handler.py](https://huggingface.co/pixai-labs/pixai-tagger-v0.9) |
| JTP（safetensors） | 等比缩放至不超过 **384**（LANCZOS）+ **RGBA 灰底(0.5)合成** + 归一化到 **[-1, 1]**（mean=std=0.5）+ 中心裁剪 384，输入布局 **NCHW**；CUDA 下 fp16 | [ComfyUI-FD-Tagger/redrocket](https://github.com/StartHua/ComfyUI-FD-Tagger) |

- onnx 输入高度与布局（NHWC/NCHW）在加载时从模型元数据动态读取，不硬编码
- onnxruntime 优先尝试 CUDA，失败自动回退 CPU

### 3. 概率输出

三个引擎的输出均已包含 sigmoid 激活（概率 0~1），代码直接与阈值比较，不再二次激活。
（JTP v2 为门控头 `sigmoid(x) × sigmoid(gate)`，v1 头输出经 sigmoid，均已是概率。）

### 4. 种子机制

- **随机**：每次点击「运行」时自动生成新的 **15 位随机种子**（界面同步显示），打乱标签顺序；每次运行顺序都不同
- **固定**：标签按置信度降序排列（先评分，再按 角色→版权→艺术家→常规→元数据→质量→模型 的类别顺序拼接）；种子数字与上次一致时**跳过执行**（沿用上次结果），种子变化后才执行
- 批量打标模式不受种子影响：每次运行都会重新扫描并打标

## 六、依赖

- `onnxruntime`：WD14 / deepghs ONNX 模型推理
- `timm>=0.9.0`：pixai pth 模型（内置 `eva02_large_patch14_448`）与 JTP safetensors 模型（内置 `vit_so400m_patch14_siglip_384`）架构加载，**离线构建无需联网**
- `safetensors`：JTP 权重加载（ComfyUI 自带）
- `torch`：pth / safetensors 推理（ComfyUI 自带），有 CUDA 时自动用 GPU
- 已写入插件根目录 `requirements.txt`

## 七、常见问题

| 问题 | 解决方法 |
| --- | --- |
| 节点报错「未找到任何反推模型」 | 将模型文件夹放入 `models/tagger` 后重启 ComfyUI |
| 报错「缺少标签文件」 | 模型文件旁需放置对应的标签文件（见上表） |
| pixai pth 模型加载失败 | 确认 `timm` 已安装（`pip install timm>=0.9.0`），且权重为官方 `model_v0.9.pth` |
| deepghs ONNX 版效果异常 | 该版本按 pixai 官方预处理（[-1,1]）处理，若 onnx 图内含归一化层请改用官方 pth 版 |
| JTP 模型加载失败 | 确认文件夹内有 `*.safetensors` + `tags.json`，且权重来自 [JointTaggerProject](https://huggingface.co/RedRocket/JointTaggerProject) |
| 选择 JTP 后「角色阈值」消失 | 正常现象：JTP 标签无类别之分，界面已自动隐藏不支持的二级参数 |
| 反推结果为空 | 降低「常规阈值」；确认对应类别开关已打开 |
| 提示词里出现 `\(` `\)` | 关闭「转义括号」开关（部分采样器不需要转义） |
| 批量打标报「文件夹不存在」 | 检查「图片文件地址」是否为完整绝对路径（不支持相对路径） |
| 批量打标报「未找到图片文件」 | 支持格式：`.png / .jpg / .jpeg / .webp / .bmp`；子文件夹图片需打开「递归搜索子文件夹」 |

## 八、批量打标（守望-Tagger批量反推器🐢）

配合「守望-Tagger批量反推器🐢」节点可对整个本地文件夹的图片批量反推并保存 Tag 文件。

### 1. 连接方式

```
[守望-Tagger批量反推器🐢] --批量打标输出(TAGGER_BATCH)--> [守望-Tagger反推器🐢] 的「批量打标」输入口
```

连接后反推器节点自动进入**批量模式**（无需连接图片输入），使用「模型名称」下拉框所选模型对整个文件夹批量打标。

### 2. 批量节点参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 图片文件地址 | STRING | 空 | 待打标图片所在的文件夹绝对路径 |
| 打标格式 | 下拉框 | txt | 输出文件格式（当前支持 txt） |
| 附加提示词 | STRING | 空 | 逗号分隔，追加到每张图片标签的最前面（如 `masterpiece, best quality`） |
| 递归搜索子文件夹 | BOOLEAN | 关 | 开启后扫描所有子文件夹中的图片 |
| 已存在Tag文件 | 下拉框 | 忽略 | 同名 Tag 文件已存在时：忽略（保留原文件）/ 覆盖 |

### 3. 输出规则

- 每张图片生成同名的 Tag 文件：`图片名.格式`（如 `a.png` → `a.txt`），UTF-8 编码
- 标签顺序：**附加提示词在前**，模型标签按置信度降序（不打乱，保证确定性）
- 打标内容与单图模式一致：应用「替换下划线 / 转义括号」选项与角色/常规/版权开关规则
- 反推器节点输出：提示词（汇总统计文本）+ 可视化（每张图一行：文件名 + 状态 + top3 标签）

### 4. 使用示例

```
图片文件地址: D:\我的图片集\训练集
打标格式:     txt
附加提示词:   masterpiece, best quality
递归搜索:     开
已存在Tag文件: 忽略
```

→ 反推器节点选择 WD14 / pixai / JTP 模型执行，`训练集` 内所有图片（含子文件夹）批量反推，
每张图旁生成 `xxx.txt`；已存在的不覆盖。
