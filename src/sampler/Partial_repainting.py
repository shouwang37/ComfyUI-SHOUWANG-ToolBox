import latent_preview
import comfy.samplers
import comfy.sample
import torch
import math
from PIL import Image, ImageFilter
import numpy as np


def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))


def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


def to_image_tensor(t):
    """规范化图像张量为 4 维 (B, H, W, C)：视频解码输出(5D)取首帧，3D 补通道维。"""
    if t is None:
        return t
    if t.dim() == 5:  # 视频 VAE 解码输出 (B, T, H, W, C)，取第一帧
        t = t[:, 0, :, :, :]
    if t.dim() == 3:  # (B, H, W) 单通道，补通道维
        t = t.unsqueeze(-1)
    return t


def common_ksampler(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent, denoise=1.0, disable_noise=False, start_step=None, last_step=None, force_full_denoise=False):
    latent_image = latent["samples"]
    if disable_noise:
        noise = torch.zeros(latent_image.size(), dtype=latent_image.dtype, layout=latent_image.layout, device="cpu")
    else:
        batch_inds = latent["batch_index"] if "batch_index" in latent else None
        noise = comfy.sample.prepare_noise(latent_image, seed, batch_inds)

    noise_mask = None
    if "noise_mask" in latent:
        noise_mask = latent["noise_mask"]

    callback = latent_preview.prepare_callback(model, steps)
    disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
    samples = comfy.sample.sample(model, noise, steps, cfg, sampler_name, scheduler, positive, negative, latent_image,
                                  denoise=denoise, disable_noise=disable_noise, start_step=start_step, last_step=last_step,
                                  force_full_denoise=force_full_denoise, noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=seed)
    out = latent.copy()
    out["samples"] = samples
    return out


class EGCYQJB:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "节点束": ("PIPE_LINE",),
            "图像": ("IMAGE",),
            "遮罩": ("MASK",),
            "随机种子": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "迭代步数": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step":0.1, "round": 0.01}),
            "采样器": (comfy.samplers.KSampler.SAMPLERS, ),
            "调度器": (comfy.samplers.KSampler.SCHEDULERS, ),
            "降噪": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.01}),
            "重绘模式": (["原图", "填充"],),
            "遮罩延展": ("INT", {"default": 6, "min": 0, "max": 64, "step": 1}),
            "仅局部重绘": ("BOOLEAN", {"default": True}),
            "局部重绘大小": ("INT", {"default": 512, "min": 0, "max": 2048, "step": 1}),
            "重绘区域扩展": ("INT", {"default": 50, "min": 0}),
            "遮罩羽化":("INT", {"default": 5, "min": 0, "max": 100, "step": 1}),
        },
        "optional": {
            "模型": ("MODEL",),
            "正面条件": ("CONDITIONING", ),
            "负面条件": ("CONDITIONING", ),
            "vae": ("VAE",),
        }}

    RETURN_TYPES = ("PIPE_LINE", "IMAGE", "IMAGE", "MASK")
    RETURN_NAMES = ('节点束', '结果图像', '采样图', '采样遮罩')
    FUNCTION = "sample"
    CATEGORY = "守望🐢/采样器"

    def mask_crop(self, image, mask, 重绘区域扩展, 局部重绘大小=0):
        image_pil = tensor2pil(image)
        mask_pil = tensor2pil(mask)
        mask_array = np.array(mask_pil) > 0
        coords = np.where(mask_array)
        if coords[0].size == 0 or coords[1].size == 0:
            return (image, None, mask)
        x0, y0, x1, y1 = coords[1].min(), coords[0].min(), coords[1].max(), coords[0].max()
        x0 -= 重绘区域扩展
        y0 -= 重绘区域扩展
        x1 += 重绘区域扩展
        y1 += 重绘区域扩展
        x0 = max(x0, 0)
        y0 = max(y0, 0)
        x1 = min(x1, image_pil.width)
        y1 = min(y1, image_pil.height)
        cropped_image_pil = image_pil.crop((x0, y0, x1, y1))
        cropped_mask_pil = mask_pil.crop((x0, y0, x1, y1))
        if 局部重绘大小 > 0:
            min_size = min(cropped_image_pil.size)
            if min_size != 局部重绘大小:
                scale_ratio = 局部重绘大小 / min_size
                new_size = (int(cropped_image_pil.width * scale_ratio), int(cropped_image_pil.height * scale_ratio))
                cropped_image_pil = cropped_image_pil.resize(new_size, Image.LANCZOS)
                cropped_mask_pil = cropped_mask_pil.resize(new_size, Image.LANCZOS)

        cropped_image_tensor = pil2tensor(cropped_image_pil)
        cropped_mask_tensor = pil2tensor(cropped_mask_pil)
        return (cropped_image_tensor, cropped_mask_tensor, (y0, y1, x0, x1))

    def encode(self, vae, image, mask, 遮罩延展=6, 重绘模式="填充"):
        x = (image.shape[1] // 8) * 8
        y = (image.shape[2] // 8) * 8
        mask = torch.nn.functional.interpolate(mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1])),
                                               size=(image.shape[1], image.shape[2]), mode="bilinear")
        if 重绘模式 == "填充":
            image = image.clone()
            if image.shape[1] != x or image.shape[2] != y:
                x_offset = (image.shape[1] % 8) // 2
                y_offset = (image.shape[2] % 8) // 2
                image = image[:, x_offset:x + x_offset, y_offset:y + y_offset, :]
                mask = mask[:, :, x_offset:x + x_offset, y_offset:y + y_offset]
        if 遮罩延展 == 0:
            mask_erosion = mask
        else:
            kernel_tensor = torch.ones((1, 1, 遮罩延展, 遮罩延展))
            padding = math.ceil((遮罩延展 - 1) / 2)
            mask_erosion = torch.clamp(torch.nn.functional.conv2d(mask.round(), kernel_tensor, padding=padding), 0, 1)

        m = (1.0 - mask.round()).squeeze(1)
        if 重绘模式 == "填充":
            for i in range(3):
                image[:, :, :, i] -= 0.5
                image[:, :, :, i] *= m
                image[:, :, :, i] += 0.5
        t = vae.encode(image)
        return {"samples": t, "noise_mask": (mask_erosion[:, :, :x, :y].round())}

    def paste_cropped_image_with_mask(self, original_image, cropped_image, crop_coords, mask, MHmask, 遮罩羽化):
        y0, y1, x0, x1 = crop_coords
        original_image_pil = tensor2pil(original_image)
        cropped_image_pil = tensor2pil(cropped_image)
        mask_pil = tensor2pil(mask)
        crop_size = (x1 - x0, y1 - y0)

        cropped_image_pil = cropped_image_pil.resize(crop_size, Image.LANCZOS)
        mask_pil = mask_pil.resize(crop_size, Image.LANCZOS)

        blurred_mask = mask_pil.convert('L')
        cropped_image_pil = cropped_image_pil.convert('RGBA')
        original_image_pil = original_image_pil.convert('RGBA')
        original_image_pil.paste(cropped_image_pil, (x0, y0), mask=blurred_mask)
        IMAGEEE = pil2tensor(original_image_pil.convert('RGB'))

        maskecmh = None
        if 遮罩羽化 is not None and 遮罩羽化 > -1:
            maskecmh = tensor2pil(MHmask).filter(ImageFilter.GaussianBlur(遮罩羽化))
        dyzz = pil2tensor(maskecmh)

        destination = to_image_tensor(original_image)
        source = to_image_tensor(IMAGEEE)
        multiplier = 8
        mask = dyzz
        destination = destination.clone().movedim(-1, 1)
        source = source.clone().movedim(-1, 1)
        source = source.to(destination.device)
        source = torch.nn.functional.interpolate(source, size=(destination.shape[2], destination.shape[3]), mode="bilinear")
        source = comfy.utils.repeat_to_batch_size(source, destination.shape[0])
        x = 0
        y = 0
        x = max(-source.shape[3] * multiplier, min(x, destination.shape[3] * multiplier))
        y = max(-source.shape[2] * multiplier, min(y, destination.shape[2] * multiplier))

        left, top = (x // multiplier, y // multiplier)
        right, bottom = (left + source.shape[3], top + source.shape[2],)

        if mask is None:
            mask = torch.ones_like(source)
        else:
            mask = mask.to(destination.device, copy=True)
            mask = torch.nn.functional.interpolate(mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1])), size=(source.shape[2], source.shape[3]), mode="bilinear")
            mask = comfy.utils.repeat_to_batch_size(mask, source.shape[0])
        visible_width, visible_height = (destination.shape[3] - left + min(0, x), destination.shape[2] - top + min(0, y),)
        mask = mask[:, :, :visible_height, :visible_width]
        inverse_mask = torch.ones_like(mask) - mask
        source_portion = mask * source[:, :, :visible_height, :visible_width]
        destination_portion = inverse_mask * destination[:, :, top:bottom, left:right]
        destination[:, :, top:bottom, left:right] = source_portion + destination_portion
        zztx = destination.movedim(1, -1)
        return zztx, dyzz

    def sample(self, pipe=None, model=None, seed=0, steps=20, cfg=8.0, sampler_name=None, scheduler=None, positive=None, negative=None, image=None, vae=None, mask=None, 遮罩延展=6, 重绘模式="填充", denoise=1.0, 仅局部重绘=False, 重绘区域扩展=0, 局部重绘大小=0, 遮罩羽化=1):
        # 从 Easy-Use 束（PIPE_LINE）中提取模型/条件/VAE/CLIP，未单独连接时自动取用束内数据
        clip = None
        if pipe is not None:
            if model is None:
                model = pipe.get("model")
            if positive is None:
                positive = pipe.get("positive")
            if negative is None:
                negative = pipe.get("negative")
            if vae is None:
                vae = pipe.get("vae")
            clip = pipe.get("clip")
        original_image = image
        hqccimage = tensor2pil(image)
        sfmask = tensor2pil(mask)
        sfhmask = sfmask.resize(hqccimage.size, Image.LANCZOS)
        mask = pil2tensor(sfhmask)
        MHmask = mask

        if 仅局部重绘:
            image, mask, crop_coords = self.mask_crop(image, mask, 重绘区域扩展, 局部重绘大小)
            latent_image = self.encode(vae, image, mask, 遮罩延展, 重绘模式)
            samples = common_ksampler(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=denoise)
            decoded_image = vae.decode(samples["samples"])
            final_image, dyzz = self.paste_cropped_image_with_mask(original_image, decoded_image, crop_coords, mask, MHmask, 遮罩羽化)
            out_pipe = {
                "model": model,
                "positive": positive,
                "negative": negative,
                "vae": vae,
                "clip": clip,
                "samples": samples["samples"],
                "images": final_image,
                "loader_settings": {
                    "seed": seed, "steps": steps, "cfg": cfg,
                    "sampler_name": sampler_name, "scheduler": scheduler, "denoise": denoise,
                },
            }
            return (out_pipe, final_image, decoded_image, dyzz)
        else:
            latent_image = self.encode(vae, image, mask, 遮罩延展, 重绘模式)
            samples = common_ksampler(model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=denoise)
            decoded_image = vae.decode(samples["samples"])

            maskecmh = None
            if 遮罩羽化 is not None and 遮罩羽化 > -1:
                maskecmh = tensor2pil(mask).filter(ImageFilter.GaussianBlur(遮罩羽化))
            dyzz = pil2tensor(maskecmh)
            mask = dyzz
            destination = to_image_tensor(original_image)
            source = to_image_tensor(decoded_image)
            multiplier = 8
            destination = destination.clone().movedim(-1, 1)
            source = source.clone().movedim(-1, 1)
            source = source.to(destination.device)
            source = torch.nn.functional.interpolate(source, size=(destination.shape[2], destination.shape[3]), mode="bilinear")
            source = comfy.utils.repeat_to_batch_size(source, destination.shape[0])
            x = 0
            y = 0
            x = max(-source.shape[3] * multiplier, min(x, destination.shape[3] * multiplier))
            y = max(-source.shape[2] * multiplier, min(y, destination.shape[2] * multiplier))

            left, top = (x // multiplier, y // multiplier)
            right, bottom = (left + source.shape[3], top + source.shape[2],)

            if mask is None:
                mask = torch.ones_like(source)
            else:
                mask = mask.to(destination.device, copy=True)
                mask = torch.nn.functional.interpolate(mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1])), size=(source.shape[2], source.shape[3]), mode="bilinear")
                mask = comfy.utils.repeat_to_batch_size(mask, source.shape[0])
            visible_width, visible_height = (destination.shape[3] - left + min(0, x), destination.shape[2] - top + min(0, y),)
            mask = mask[:, :, :visible_height, :visible_width]
            inverse_mask = torch.ones_like(mask) - mask
            source_portion = mask * source[:, :, :visible_height, :visible_width]
            destination_portion = inverse_mask * destination[:, :, top:bottom, left:right]
            destination[:, :, top:bottom, left:right] = source_portion + destination_portion
            zztx = destination.movedim(1, -1)
            out_pipe = {
                "model": model,
                "positive": positive,
                "negative": negative,
                "vae": vae,
                "clip": clip,
                "samples": samples["samples"],
                "images": zztx,
                "loader_settings": {
                    "seed": seed, "steps": steps, "cfg": cfg,
                    "sampler_name": sampler_name, "scheduler": scheduler, "denoise": denoise,
                },
            }
            return (out_pipe, zztx, decoded_image, dyzz)


NODE_CLASS_MAPPINGS = {
    "ShouWangLocalRepaintSampler": EGCYQJB,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangLocalRepaintSampler": "守望-局部重绘采样器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
