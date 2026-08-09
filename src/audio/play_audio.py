import math
import os
import random
import string
import wave

import numpy as np
import torch
from aiohttp import web

import folder_paths
from server import PromptServer


# 「音频地址」下拉为空时的占位选项
NO_AUDIO_PLACEHOLDER = "(无音频文件)"


def _register_audio_files_route():
    """注册前端刷新下拉列表的路由；PromptServer 未实例化（非 ComfyUI 启动环境）时跳过"""
    server_instance = getattr(PromptServer, "instance", None)
    if server_instance is None:
        return

    @server_instance.routes.get("/shouwang/audio_files")
    async def _shouwang_audio_files(request):
        """返回 assets/audio 文件夹中的音频文件名"""
        return web.json_response({"files": PlayAudio._list_audio_files()})


_register_audio_files_route()


def _generate_filename() -> str:
    """生成随机 wav 文件名（临时预览用）"""
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    return f"shouwang_audio_{suffix}.wav"


# 支持的音频扩展名（PyAV 解码），扫描音频文件夹时按此筛选
AUDIO_FILE_EXTENSIONS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus")


def _waveform_to_wav(audio: dict, filepath: str) -> None:
    """将 AUDIO 字典（waveform / sample_rate）写为 16bit PCM wav 文件"""
    waveform = audio["waveform"]  # (batch, channels, samples)
    sample_rate = int(audio["sample_rate"])
    data = waveform[0].detach().cpu().numpy()  # (channels, samples)
    if data.ndim == 1:
        data = data[None, :]
    # 转交织布局 (samples, channels) 并量化到 int16
    interleaved = data.transpose(1, 0)
    pcm = np.clip(interleaved * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(data.shape[0])
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


class PlayAudio:
    """浏览器播放音频提醒节点：
    - 「触发输入」为必填任意类型端口，只有接入数据执行到该节点才播放所选音频提醒用户
    - 「音频地址」下拉选择插件目录 assets/audio 文件夹中的音频文件
    - 播放的音频由前端 web/play_audio.js 从临时目录拉取
    """

    @classmethod
    def INPUT_TYPES(cls):
        audio_files = cls._list_audio_files() or [NO_AUDIO_PLACEHOLDER]
        return {
            "required": {
                "音频地址": (audio_files, {"default": audio_files[0]}),
                "音量": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "时长限制": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 300.0, "step": 0.1}),
            },
            "optional": {
                "触发输入": ("*",),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "play_audio"
    OUTPUT_NODE = True
    CATEGORY = "守望🐢/音频"
    DESCRIPTION = "播放提醒节点：「触发输入」为必填任意类型端口，必须接入数据执行到该节点才播放音频；「音频地址」下拉选择 assets/audio 文件夹中的音频文件。时长限制 0 表示完整播放。"

    @staticmethod
    def _generate_beep() -> dict:
        """无音频输入时生成一声 880Hz 提示音"""
        sample_rate = 32000
        t = torch.linspace(0, 0.3, int(sample_rate * 0.3))
        tone = torch.tanh(3 * torch.sin(2 * math.pi * 880 * t)) * 0.3
        return {"waveform": tone.unsqueeze(0).unsqueeze(0), "sample_rate": sample_rate}

    @staticmethod
    def _read_wav_stdlib(path: str) -> dict:
        """标准库 wave 解码 16bit/32bit PCM wav，返回 AUDIO 字典"""
        with wave.open(path, "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        if sampwidth == 2:
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"不支持的 wav 位深：{sampwidth * 8}bit（仅支持 16/32bit PCM）")
        pcm = pcm.reshape(-1, channels).transpose(1, 0)  # (channels, samples)
        return {"waveform": torch.from_numpy(pcm).unsqueeze(0), "sample_rate": sample_rate}

    @staticmethod
    def _load_audio_file(path: str) -> dict:
        """解码音频文件为 AUDIO 字典：优先 PyAV（mp3/flac/ogg/m4a 等），wav 可回退标准库"""
        try:
            import av
        except ImportError:
            av = None
        if av is not None:
            # metadata_errors=replace：容忍非 UTF-8 编码的中文 ID3 标签（如 GBK），不因标签乱码中断解码
            with av.open(path, metadata_errors="replace") as af:
                stream = af.streams.audio[0]
                sample_rate = stream.codec_context.sample_rate
                frames = []
                for frame in af.decode(streams=stream.index):
                    buf = torch.from_numpy(frame.to_ndarray())
                    if buf.shape[0] != stream.channels:
                        buf = buf.view(-1, stream.channels).t()
                    # 归一化到 [-1, 1]：整型解码器（如 wav s16/s32）需缩放，浮点解码器（如 mp3）直接使用
                    if buf.dtype == torch.int16:
                        buf = buf.float() / 32768.0
                    elif buf.dtype == torch.int32:
                        buf = buf.float() / 2147483648.0
                    else:
                        buf = buf.float()
                    frames.append(buf)
                waveform = torch.cat(frames, dim=1)
            return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
        if path.lower().endswith(".wav"):
            return PlayAudio._read_wav_stdlib(path)
        raise ValueError(f"缺少 PyAV 依赖，无法解码非 wav 音频：{path}（请 pip install av）")

    @staticmethod
    def _audio_folder() -> str:
        """音频文件夹（唯一）：插件目录下的 assets/audio"""
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(plugin_dir, "assets", "audio")

    @staticmethod
    def _list_audio_files() -> list:
        """扫描音频文件夹，返回按名称排序的音频文件名列表（文件夹不存在返回空）"""
        folder = PlayAudio._audio_folder()
        if not os.path.isdir(folder):
            return []
        return sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith(AUDIO_FILE_EXTENSIONS)
        )

    @staticmethod
    def _load_selected(filename: str):
        """加载「音频地址」选中的文件（音频文件夹下）；无选中或文件缺失返回 None"""
        filename = filename.strip()
        if not filename or filename == NO_AUDIO_PLACEHOLDER:
            return None
        resolved = os.path.join(PlayAudio._audio_folder(), filename)
        if os.path.isfile(resolved):
            return PlayAudio._load_audio_file(resolved)
        print(f"[守望-播放音频] 找不到音频文件 {resolved}，使用提示音")
        return None

    def play_audio(self, 触发输入=None, 音频地址=NO_AUDIO_PLACEHOLDER, 音量=0.5, 时长限制=5.0):
        # 触发输入未接入任何数据时不播放（静默返回，不生成音频）
        if 触发输入 is None:
            return {}

        音频 = self._load_selected(音频地址)
        if 音频 is None:
            音频 = self._generate_beep()

        filename = _generate_filename()
        filepath = os.path.join(folder_paths.get_temp_directory(), filename)
        _waveform_to_wav(音频, filepath)

        return {
            "ui": {
                "audio": [{"filename": filename, "subfolder": "", "type": "temp"}],
            }
        }


NODE_CLASS_MAPPINGS = {
    "ShouWangPlayAudio": PlayAudio,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangPlayAudio": "守望-提示音频🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
