/**
 * ComfyUI-SHOUWANG-ToolBox — 播放音频节点前端扩展
 *
 * 参考 KJNodes PlaySoundKJ 的 web/js/play_sound.js：
 * 「触发输入」有数据接入执行到该节点时，每次执行都播放所选音频。
 * 时长限制 > 0 时到时自动停止（0 = 完整播放）。
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_TYPE = "ShouWangPlayAudio";

app.registerExtension({
    name: "SHOUWANG.PlayAudio",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // 节点创建后刷新「音频地址」下拉列表（保留当前选择，不存在则切到第一个）
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            this._swRefreshAudioFiles();
        };

        nodeType.prototype._swRefreshAudioFiles = async function () {
            try {
                const resp = await api.fetchApi("/shouwang/audio_files");
                const data = await resp.json();
                const widget = this.widgets?.find(w => w.name === "音频地址");
                if (!widget) return;
                const files = Array.isArray(data?.files) ? data.files : [];
                widget.options = { values: files.length ? files : ["(无音频文件)"] };
                if (!files.includes(widget.value)) {
                    widget.value = files[0] ?? "(无音频文件)";
                }
            } catch (e) {
                // 后端不可用或尚未就绪时跳过刷新
            }
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (output) {
            onExecuted?.apply(this, arguments);

            const audios = output?.audio;
            if (!audios?.length) return;

            const volumeWidget = this.widgets?.find(w => w.name === "音量");
            const durationWidget = this.widgets?.find(w => w.name === "时长限制");
            const volume = volumeWidget?.value ?? 0.5;
            const duration = durationWidget?.value ?? 5.0;

            if (this._swPlayingAudio) {
                this._swPlayingAudio.pause();
                this._swPlayingAudio = null;
            }
            if (this._swPlayTimer != null) {
                clearTimeout(this._swPlayTimer);
                this._swPlayTimer = null;
            }

            const { filename, subfolder, type } = audios[0];
            const params = new URLSearchParams({
                filename: filename ?? "",
                subfolder: subfolder ?? "",
                type: type ?? "temp",
            });
            const url = api.apiURL(`/view?${params.toString()}`);
            const audio = new Audio(url);
            audio.volume = Math.max(0, Math.min(1, volume));
            audio.play().catch(() => {});
            this._swPlayingAudio = audio;
            if (duration > 0) {
                this._swPlayTimer = setTimeout(() => {
                    audio.pause();
                    this._swPlayingAudio = null;
                    this._swPlayTimer = null;
                }, duration * 1000);
            }
        };
    },
});
