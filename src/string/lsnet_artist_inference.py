"""守望-LSNet风格反推器:使用 LSNet 画师风格分类模型对图像进行画师风格反推。

参考 comfyui-lsnet 的 LSNet Artist Inference 节点移植:
- 输入图像 + LSNET_MODEL 模型包(由守望-LSNet模型加载器提供)
- 输出 Top-K 画师标签字符串(逗号分隔)与 JSON 概率字典
"""

import json

import torch
import torch.nn.functional as F
from PIL import Image


class LSNetArtistInference:
    """「守望-LSNet风格反推器」:输入图像,反推 Top-K 画师风格标签及其概率。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "模型": ("LSNET_MODEL",),
                "top_k": ("INT", {"default": 5, "min": 1, "max": 100}),
                "阈值": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("标签", "JSON结果")
    FUNCTION = "process"
    CATEGORY = "守望🐢/提示词"
    DESCRIPTION = "使用 LSNet 画师风格模型对图像进行风格反推，输出 Top-K 画师标签（逗号分隔）与 JSON 概率字典，适合为图像匹配画师风格提示词。"

    def process(self, 图像, 模型, top_k, 阈值):
        model_bundle = 模型
        model = model_bundle['model']
        transform = model_bundle['transform']
        class_mapping = model_bundle['class_mapping']
        device = model_bundle['device']

        if 图像.ndim == 4:
            图像 = 图像[0]
        图像 = (图像 * 255).clamp(0, 255).byte().cpu().numpy()
        pil_image = Image.fromarray(图像)

        # Preprocess image
        image_tensor = transform(pil_image).unsqueeze(0)  # Add batch dimension

        # Classify
        with torch.no_grad():
            image_tensor = image_tensor.to(device)
            logits = model(image_tensor, return_features=False)
            probs = F.softmax(logits, dim=-1)
            top_probs, top_indices = torch.topk(probs, k=min(top_k, probs.size(-1)), dim=-1)

            results = []
            for prob, idx in zip(top_probs[0].cpu().numpy(), top_indices[0].cpu().numpy()):
                if prob >= 阈值:
                    class_id = int(idx)
                    class_name = class_mapping.get(class_id, f"Class {class_id}")
                    results.append({
                        'class_id': class_id,
                        'class_name': class_name,
                        'probability': float(prob)
                    })

            # Limit to top_k if more results after filtering
            if len(results) > top_k:
                results = results[:top_k]

        # Prepare outputs
        tags = [res['class_name'] for res in results]
        tag_string = ",".join(tags)
        tag_dict = {res['class_name']: res['probability'] for res in results}
        json_output = json.dumps(tag_dict, ensure_ascii=False)

        return (tag_string, json_output)


NODE_CLASS_MAPPINGS = {
    "ShouWangLSNetArtistInference": LSNetArtistInference,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangLSNetArtistInference": "守望-LSNet风格反推器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
