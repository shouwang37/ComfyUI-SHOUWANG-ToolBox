# ComfyUI-SHOUWANG-ToolBox

![Logo](./assets/img/卞玥_蓝玫映月_2.jpg)

## 简介

#### ComfyUI-SHOUWANG-ToolBox 是一个为 ComfyUI 设计的自定义节点集合，提供了一系列实用工具为使用者更好的搭建半自动化、构建图像处理工作流，感谢再见我们下次再见。

## 节点介绍

## 提示词类

### 1.提示词反推

![采样器 UP放大](./assets/img/%E6%8F%90%E7%A4%BA%E8%AF%8D%20%E5%8F%8D%E6%8E%A8.png)

#### 支持的模型：

以下模型已测试支持（放入 `models/tagger` 目录，按文件夹名选择）：

| 模型名称                           | 文件夹名（放置名）         | 模型文件        | 标签文件            | 下载地址                                                     |
| ---------------------------------- | -------------------------- | --------------- | ------------------- | ------------------------------------------------------------ |
| WD EVA02-Large Tagger v3           | `wd-eva02-large-tagger-v3` | `model.onnx`    | `selected_tags.csv` | [SmilingWolf/wd-eva02-large-tagger-v3](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) |
| cl_tagger_1_02                     | `cl_tagger_1_02`           | `model.onnx`    | `tag_mapping.json`  | [cella110n/cl_tagger](https://huggingface.co/cella110n/cl_tagger/blob/main/cl_tagger_1_02) |
| PixAI Tagger v0.9（ONNX 兼容）     | `pixai-tagger-v0.9-onnx`   | `model.onnx`    | `tag_mapping.json`  | [deepghs/pixai-tagger-v0.9-onnx](https://huggingface.co/deepghs/pixai-tagger-v0.9-onnx) |
| JTP PILOT2（FD-Tagger，e621 风格） | `JTP_PILOT2`               | `*.safetensors` | `tags.json`         | [RedRocket/JointTaggerProject](https://huggingface.co/RedRocket/JointTaggerProject) |

#### 模型放置方法：

模型统一放在 **ComfyUI 全局 models 目录下的 tagger 文件夹**（唯一位置，即 `../models/tagger`）：

ComfyUI/models/tagger/wd-eva02-large-tagger-v3/
├── model.onnx
└── selected_tags.csv

ComfyUI/models/tagger/cl_tagger_1_02/
├── model.onnx
└── tag_mapping.json

ComfyUI/models/tagger/pixai-tagger-v0.9-onnx/
├── model.onnx
└── tag_mapping.json

ComfyUI/models/tagger/JTP_PILOT2/
├── JTP_PILOT2-e3-vit_so400m_patch14_siglip_384.safetensors
└── tags.json
### 2.提示词 反推批量

![Logo](./assets/img/%E6%8F%90%E7%A4%BA%E8%AF%8D%20%E5%8F%8D%E6%8E%A8%E6%89%B9%E9%87%8F.png)

#### 在前者的基础上配置了批量反推的插件

### 3.提示词 提示词处理

![Logo](./assets/img/%E6%8F%90%E7%A4%BA%E8%AF%8D%20%E6%8F%90%E7%A4%BA%E8%AF%8D%E5%A4%84%E7%90%86.png)

#### 提示词的规格化、剔除不需要的提示词如水印、审核、马赛克等提示词tag、提示词合并处理、提示词替换

## 图像类

### 1.图像 TTP拼接

![Logo](./assets/img/%E5%9B%BE%E5%83%8F%20TTP%E6%8B%BC%E6%8E%A5.png)

#### 适用原图像放大的TTP节点图像分块拆分在此感谢原作者的开源

### 2.图像 按边缩放

![Logo](./assets/img/%E5%9B%BE%E5%83%8F%20%E6%8C%89%E8%BE%B9%E7%BC%A9%E6%94%BE.png)

#### 按图像的长或短边在倍数或者分辨率的情况下进行缩放

### 3.图像 滑动对比

![Logo](./assets/img/%E5%9B%BE%E5%83%8F%20%E6%BB%91%E5%8A%A8%E5%AF%B9%E6%AF%94.png)

### 两张图片重叠在一起通过滑动滑块比较之间的区别

### 4.图像 拼接对比

![Logo](./assets/img/%E5%9B%BE%E5%83%8F%20%E6%8B%BC%E6%8E%A5%E5%AF%B9%E6%AF%94.png)

#### 可以添加任意的组别设置标题将图片拼接在一起进行拼接对比

### 5.图像裁切

![Logo](./assets/img/%E5%9B%BE%E5%83%8F%20%E5%8C%BA%E5%9F%9F%E6%8B%BC%E6%8E%A5%E9%87%8D%E7%BB%98.png)

#### 通过绘制遮罩截取需要处理的图片区域在处理完成之后通过数据拼接回原图像之上不必手动矫正

## 音频类

### 1.音频 提示音频

![Logo](./assets/img/%E9%9F%B3%E9%A2%91%20%E6%8F%90%E7%A4%BA%E9%9F%B3%E9%A2%91.png)

#### 可以接入任意节点之后在运行至该节点触发设置的音频提示

## 工具类

### 1.工具 从本地加载或储存

![采样器 UP放大](./assets/img/%E5%B7%A5%E5%85%B7%20%E4%BB%8E%E6%9C%AC%E5%9C%B0%E5%8A%A0%E8%BD%BD.png)

#### 从本地文件夹加载文件,储存图片至指定路径文件夹前缀为空则用原图像名储存

### 2.工具 禁用忽略队组 书签

![采样器 UP放大](./assets/img/%E5%B7%A5%E5%85%B7%20%E5%BF%BD%E7%95%A5%E5%BF%BD%E7%95%A5%E5%A4%9A%E7%BB%84%E4%B9%A6%E7%AD%BE.png)

#### 禁用多组 忽略多组 设置书签按数字键跳转

### 3. 工具 取色器

![采样器 UP放大](./assets/img/%E5%B7%A5%E5%85%B7%20%E5%8F%96%E8%89%B2%E5%99%A8.png)

#### 滑动颜色区域选色或者点击屏幕取色获取颜值数值

### 4.工具 外补画板

![采样器 UP放大](./assets/img/%E5%B7%A5%E5%85%B7%20%E5%A4%96%E8%A1%A5%E7%94%BB%E6%9D%BF.png)

#### 向原图像四周扩展像素值并填空需求颜色可选透明

### 5.工具 任意切换

![采样器 UP放大](./assets/img/%E5%B7%A5%E5%85%B7%20%E4%BB%BB%E6%84%8F%E5%88%87%E6%8D%A2.png)

#### 根据输入的类型数量模式有选择或者顺序来决定输出的序号位

## 采样器类

### 1. 采样器 UP放大

![采样器 UP放大](./assets/img/%E9%87%87%E6%A0%B7%E5%99%A8%20UP%E6%94%BE%E5%A4%A7.png)

#### 适用于模型放大但配置了pipe输入节点

### 2.采样器 局部重绘

![采样器 UP放大](./assets/img/%E9%87%87%E6%A0%B7%E5%99%A8%20%E5%B1%80%E9%83%A8%E9%87%87%E6%A0%B7%E9%87%8D%E7%BB%98%E5%99%A8.png)

#### 适用于一定区域进行局部重绘且不影响其他区域的高级重绘节点

### v1.0.0

- 初始版本发布

## 贡献

欢迎提交Issue和Pull Request来帮助改进这个项目！

## 许可证

MIT License

## 感谢

在此参考了以下节点的源码十分感谢

- https://github.com/yolain/ComfyUI-Easy-Use
- https://github.com/TTPlanetPig/Comfyui_TTP_Toolset
- https://github.com/rgthree/rgthree-comfy
- https://github.com/11dogzi/Comfyui-ergouzi-Nodes

## 联系方式

如有问题或建议，请通过以下方式联系：

- QQ群聊:552419016

---

*感谢使用ComfyUI-SHOUWANG-ToolBox！*
