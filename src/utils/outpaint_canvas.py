"""守望-外补画板节点：扩展画布并输出重绘遮罩（原版 ImagePadForOutpaint 升级版）。

参考 ComfyUI 原版 Pad Image for Outpainting：
- 上下左右按像素扩展，原图居中粘贴
- 遮罩语义：扩展区=1（需重绘），原图内部=0（保留），原图边缘按 v² 渐变羽化过渡
升级点：
- 「颜色」支持 rgb（"255,0,0" / "rgb(...)" / "rgba(...)"）与十六进制（"#RRGGBB" / "#RGB"），
  替代原版固定中灰填充
- 「填充为透明」开启时输出 RGBA：扩展区 alpha=0（原图保持），颜色参数被忽略
- 图像羽化：扩展区按到原图边界的距离与原图边缘像素线性混合，消除交界色差
"""

import re

import torch
import torch.nn.functional as F


class ShouWangOutpaintCanvas:
    """「外补画板」节点：四边扩展画布，输出扩展图像与重绘遮罩（含羽化）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "上": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "下": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "左": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "右": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 8}),
                "羽化": ("INT", {"default": 40, "min": 0, "max": 16384, "step": 1}),
                # 支持 rgb 与十六进制：如 "#FF0000"、"255,0,0"、"rgb(255,0,0)"
                "颜色": ("STRING", {"default": "#808080"}),
                "填充为透明": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("图片", "遮罩")
    FUNCTION = "expand"
    CATEGORY = "守望🐢/工具"
    DESCRIPTION = "外补画板（原版 Pad Image for Outpainting 升级版）：上下左右按像素扩展画布并输出重绘遮罩；支持 rgb/十六进制填充颜色与透明填充。"

    @staticmethod
    def _parse_color(text):
        """解析颜色：支持 "#RRGGBB" / "#RGB"、"255,0,0"、"rgb(...)" / "rgba(...)"，非法时回退 None。"""
        if text is None:
            return None
        s = str(text).strip().lower()
        if s.startswith("#"):
            hexs = s[1:]
            if len(hexs) == 3:
                hexs = "".join(c * 2 for c in hexs)
            if len(hexs) >= 6:
                try:
                    return tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))
                except ValueError:
                    pass
        m = re.search(r"rgba?\((.*?)\)", s)
        if m:
            s = m.group(1)
        parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
        if len(parts) >= 3:
            try:
                return tuple(max(0, min(255, int(float(p)))) for p in parts[:3])
            except ValueError:
                pass
        return None

    def expand(self, 图像, 上, 下, 左, 右, 羽化, 颜色, 填充为透明):
        d1, d2, d3, d4 = 图像.size()
        H, W = d2 + 上 + 下, d3 + 左 + 右
        dev = 图像.device

        # 填充颜色（0~1），解析失败回退中灰（与原版一致）
        rgb = self._parse_color(颜色)
        if rgb is None:
            rgb = (128, 128, 128)
        fill = torch.tensor(rgb, dtype=torch.float32, device=dev) / 255.0

        if 填充为透明:
            # RGBA：扩展区 alpha=0，原图 alpha=1
            if d4 == 3:
                图像 = torch.cat([图像, torch.ones((d1, d2, d3, 1), device=dev)], dim=-1)
            new_image = torch.zeros((d1, H, W, 4), dtype=torch.float32, device=dev)
            new_image[:, 上:上 + d2, 左:左 + d3, :] = 图像
        else:
            if d4 == 4:
                fill = torch.cat([fill, torch.ones(1, device=dev)])
            new_image = fill.view(1, 1, 1, -1).expand(d1, H, W, -1).clone()
            new_image[:, 上:上 + d2, 左:左 + d3, :] = 图像

            # 图像羽化：扩展区按到原图边界的距离与原图边缘像素线性混合
            if 羽化 > 0 and (H > d2 or W > d3):
                ys = torch.arange(H, device=dev).view(H, 1)
                xs = torch.arange(W, device=dev).view(1, W)
                dist_h = torch.maximum(左 - xs, xs - (左 + d3 - 1))  # 正 = 原图矩形外
                dist_v = torch.maximum(上 - ys, ys - (上 + d2 - 1))
                dist = torch.maximum(dist_h, dist_v).clamp(min=0)
                mix = (dist / 羽化).clamp(max=1.0)  # 0=紧贴原图边缘，1=纯填充色
                if mix.any():
                    # 原图边缘复制扩展，与填充色按距离混合
                    padded = F.pad(图像, (0, 0, 左, 右, 上, 下), mode="replicate")
                    mix4 = mix.view(1, H, W, 1)
                    new_image = padded * (1 - mix4) + new_image * mix4

        # 遮罩：扩展区=1（需重绘），原图内部=0，边缘 v² 渐变（参考原版 ImagePadForOutpaint）
        # 注意：距离场仅在已扩展的方向计算（未扩展方向的边不产生羽化渐变，与原版一致）
        mask = torch.ones((H, W), dtype=torch.float32, device=dev)
        if 羽化 > 0 and 羽化 * 2 < d2 and 羽化 * 2 < d3:
            iy = torch.arange(d2, device=dev).view(d2, 1)
            jx = torch.arange(d3, device=dev).view(1, d3)
            dt = iy if 上 != 0 else torch.full_like(iy, d2)
            db = (d2 - 1 - iy) if 下 != 0 else torch.full_like(iy, d2)
            dl = jx if 左 != 0 else torch.full_like(jx, d3)
            dr = (d3 - 1 - jx) if 右 != 0 else torch.full_like(jx, d3)
            d = torch.minimum(torch.minimum(dt, db), torch.minimum(dl, dr))
            v = ((羽化 - d) / 羽化).clamp(min=0.0, max=1.0)
            mask[上:上 + d2, 左:左 + d3] = v * v
        else:
            mask[上:上 + d2, 左:左 + d3] = 0.0

        return (new_image, mask.unsqueeze(0))


NODE_CLASS_MAPPINGS = {
    "ShouWangOutpaintCanvas": ShouWangOutpaintCanvas,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangOutpaintCanvas": "守望-外补画板🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
