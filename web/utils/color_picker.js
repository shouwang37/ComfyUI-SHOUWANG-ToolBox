/**
 * ComfyUI-SHOUWANG-ToolBox — 取色器节点前端扩展
 *
 * 参考 PS 取色器交互，节点内 DOM canvas 绘制：
 *   - 方形色域：横轴饱和度、纵轴明度（上亮下暗），色相由下方滑条决定
 *   - 色相渐变滑条：放大加宽，点击/拖拽改变色相（判定优先于色域，带容差）
 *   - 预览行：醒目色块 + 颜色值文本（跟随「颜色类型」参数）+ 复制按钮（点击复制当前颜色值到剪贴板）
 *   - 屏幕取色按钮：点击弹出系统取色器（EyeDropper，不可用时回退原生颜色选择器）
 * 选色写入隐藏的「颜色值」widget（r,g,b），执行时传给后端生成纯色图片；
 * 「随机颜色」模式下后端执行后回传实际颜色，前端同步取色器显示。
 */

import { app } from "../../../scripts/app.js";

const NODE_TYPE = "ShouWangColorPicker";
const PAD = 8;      // 内容边距
const HUE_H = 22;   // 色相条高度
const INFO_H = 48;  // 预览行高度
const BTN_H = 28;   // 屏幕取色按钮高度
const SWATCH_W = 96; // 预览色块宽度
const COPY_W = 60;  // 复制按钮宽度
const COPY_H = 30;  // 复制按钮高度
const GAP = 6;      // 区域间距
const DEFAULT_COLOR = [255, 0, 0]; // 与后端「颜色值」默认值一致

const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

/** HSV → RGB（h: 0-360，s/v: 0-1，返回 0-255 数组） */
const hsvToRgb = (h, s, v) => {
    const c = v * s;
    const hp = (((h % 360) + 360) % 360) / 60;
    const x = c * (1 - Math.abs((hp % 2) - 1));
    const m = v - c;
    let r = 0, g = 0, b = 0;
    if (hp < 1) [r, g, b] = [c, x, 0];
    else if (hp < 2) [r, g, b] = [x, c, 0];
    else if (hp < 3) [r, g, b] = [0, c, x];
    else if (hp < 4) [r, g, b] = [0, x, c];
    else if (hp < 5) [r, g, b] = [x, 0, c];
    else [r, g, b] = [c, 0, x];
    return [
        Math.round((r + m) * 255),
        Math.round((g + m) * 255),
        Math.round((b + m) * 255),
    ];
};

/** RGB → HSV（返回 [h: 0-360, s: 0-1, v: 0-1]） */
const rgbToHsv = ([r, g, b]) => {
    const rn = r / 255, gn = g / 255, bn = b / 255;
    const max = Math.max(rn, gn, bn);
    const min = Math.min(rn, gn, bn);
    const d = max - min;
    let h = 0;
    if (d !== 0) {
        if (max === rn) h = ((gn - bn) / d) % 6;
        else if (max === gn) h = (bn - rn) / d + 2;
        else h = (rn - gn) / d + 4;
        h *= 60;
        if (h < 0) h += 360;
    }
    return [Math.round(h), max === 0 ? 0 : d / max, max];
};

/** 解析颜色字符串为 0-255 数组：支持 "r,g,b" 与 "#RRGGBB" / "#RGB"；非法时返回 null */
const parseColor = (text) => {
    if (typeof text !== "string") return null;
    const s = text.trim();
    // 十六进制（EyeDropper / 原生颜色选择器返回格式）
    if (s.startsWith("#")) {
        let hex = s.slice(1);
        if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
        if (hex.length >= 6) {
            const n = parseInt(hex.slice(0, 6), 16);
            if (!Number.isNaN(n)) return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
        }
        return null;
    }
    // rgb 逗号格式
    const parts = s.split(",").map((n) => parseInt(n.trim(), 10)).filter((n) => !Number.isNaN(n));
    if (parts.length < 3) return null;
    return parts.slice(0, 3).map((c) => clamp(c, 0, 255));
};

/** 取色器 DOM widget：绘制色域/色相条/预览行，并处理选色交互 */
class ColorPickerWidget {
    constructor(node) {
        this.name = "sw_color_picker";
        this.type = "custom";
        this.node = node;
        this.dragging = null; // "picker" | "hue" | null

        this.color = [...DEFAULT_COLOR];
        const [h, s, v] = rgbToHsv(DEFAULT_COLOR);
        this.hue = h;
        this.s = s;
        this.v = v;
        this._pickerCache = null; // 色域离屏缓存（hue/尺寸未变时复用）
        this._hueCache = null;    // 色相条离屏缓存（仅按宽度缓存）
        this._hoverBtn = false;   // 鼠标悬停在屏幕取色按钮上
        this._hoverCopy = false;  // 鼠标悬停在复制按钮上
        this._copied = false;     // 复制成功反馈中（短暂显示"已复制"）

        this.canvas = document.createElement("canvas");
        this.canvas.style.width = "100%";
        this.canvas.style.height = "100%";
        this.canvas.style.display = "block";
        this.canvas.style.cursor = "crosshair";
        this.ctx = this.canvas.getContext("2d");

        // 节点尺寸变化 → canvas 尺寸变化 → 重绘（并保证高分屏清晰）
        if (typeof ResizeObserver !== "undefined") {
            this._resizeObserver = new ResizeObserver(() => this.redraw());
            this._resizeObserver.observe(this.canvas);
        }

        this.canvas.addEventListener("mousedown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.pickFromEvent(e);
        });
        // 屏幕取色：必须由左键单击（click）触发 —— EyeDropper / input[type=color] 依赖
        // user activation，mousedown 阶段调用在部分浏览器中会静默失败
        this.canvas.addEventListener("click", (e) => {
            if (!this.isScreenPickerHit(e)) return;
            e.preventDefault();
            e.stopPropagation();
            this.openScreenPicker();
        });
        this.canvas.addEventListener("mousemove", (e) => {
            if (this.dragging) this.dragFromEvent(e);
            else this.updateHover(e);
        });
        this.canvas.addEventListener("mouseup", () => { this.dragging = null; });
        this.canvas.addEventListener("mouseleave", () => { this.dragging = null; });
    }

    /** DOM widget 总高度：色域（与宽同高的方形）+ 色相条 + 预览行 + 屏幕取色按钮 */
    getHeight() {
        const width = Math.max(160, (this.node.size?.[0] ?? 256) - 16);
        return PAD + width + GAP + HUE_H + GAP + INFO_H + GAP + BTN_H + PAD;
    }

    /** 节点内各区域几何（css 像素坐标） */
    layout() {
        const cssW = this.canvas.clientWidth || Math.max(160, (this.node.size?.[0] ?? 256) - 16);
        const pickerW = cssW - PAD * 2;
        const hueY = PAD + pickerW + GAP;
        const infoY = PAD + pickerW + GAP + HUE_H + GAP;
        const btnY = PAD + pickerW + GAP + HUE_H + GAP + INFO_H + GAP;
        return {
            cssW,
            pickerX: PAD,
            pickerY: PAD,
            pickerW,
            hueY,
            infoY,
            infoH: INFO_H,
            btnY,
            btnH: BTN_H,
            copyBtnX: cssW - PAD - COPY_W,
            copyBtnY: infoY + (INFO_H - COPY_H) / 2,
            cssH: PAD + pickerW + GAP + HUE_H + GAP + INFO_H + GAP + BTN_H + PAD,
        };
    }

    /** 同步隐藏「颜色值」widget 并刷新绘制 */
    syncWidget() {
        const [r, g, b] = this.color;
        const w = this.node.widgets?.find((x) => x.name === "颜色值");
        if (w && w.value !== `${r},${g},${b}`) w.value = `${r},${g},${b}`;
        this.redraw();
    }

    /** 设置颜色（外部 RGB，如初始化/后端回传/屏幕取色），反向同步 hue/s/v */
    setColor(rgb) {
        this.color = [...rgb];
        const [h, s, v] = rgbToHsv(rgb);
        this.hue = h;
        this.s = s;
        this.v = v;
        this._pickerCache = null;
        this.syncWidget();
    }

    /**
     * 以 HSV 设置颜色（色域/色相条拖拽用）。
     * 注意：不能经 setColor 反向重算 hue —— 底部（明度≈0）时 RGB 量化取整
     * 会使 rgbToHsv 反算出的色相严重偏离（甚至归 0），导致拖动中色相被反复污染而乱跳。
     */
    setHsv(h, s, v) {
        this.hue = h;
        this.s = s;
        this.v = v;
        this.color = hsvToRgb(h, s, v);
        this._pickerCache = null;
        this.syncWidget();
    }

    /** 以 "r,g,b" 字符串应用颜色（初始化 / 后端回传 / widget 外部修改） */
    applyColor(text) {
        const rgb = parseColor(text);
        if (!rgb) return;
        const [r, g, b] = rgb;
        if (this.color[0] === r && this.color[1] === g && this.color[2] === b) return;
        this.setColor(rgb);
    }

    /**
     * 鼠标位置（相对 canvas 的 css 像素坐标）。
     * 画布缩放（zoom ≠ 1）时 getBoundingClientRect 返回缩放后的尺寸，而绘制基于
     * clientWidth 逻辑坐标，必须按比例换算回逻辑坐标，否则点击位置会偏移。
     */
    eventPos(e) {
        const rect = this.canvas.getBoundingClientRect();
        const scaleX = rect.width ? this.canvas.clientWidth / rect.width : 1;
        const scaleY = rect.height ? this.canvas.clientHeight / rect.height : 1;
        return {
            x: (e.clientX - rect.left) * scaleX,
            y: (e.clientY - rect.top) * scaleY,
        };
    }

    /** 命中「屏幕取色」按钮区域？（由 click 事件调用） */
    isScreenPickerHit(e) {
        const { cssW, pickerX, btnY, btnH } = this.layout();
        const { x, y } = this.eventPos(e);
        return y >= btnY && y <= btnY + btnH && x >= pickerX && x <= cssW - PAD;
    }

    /** mousedown：复制颜色 / 色相条与色域拖拽选色（屏幕取色改由 click 触发） */
    pickFromEvent(e) {
        const { pickerX, pickerY, pickerW, hueY, copyBtnX, copyBtnY } = this.layout();
        const { x, y } = this.eventPos(e);
        // 复制按钮：点击复制当前颜色值到剪贴板
        if (y >= copyBtnY && y <= copyBtnY + COPY_H && x >= copyBtnX && x <= copyBtnX + COPY_W) {
            this.copyColor();
            return;
        }
        // 色相条优先判定（顶部无容差，与色域底部判定间隔完整 GAP，避免边界误判导致色相瞬跳）
        if (y >= hueY && y <= hueY + HUE_H + 4) {
            this.dragging = "hue";
            this.applyPointer(x, y);
            return;
        }
        // 方形色域（底部无容差，与色相条顶部判定留出 GAP 安全区）
        if (y >= pickerY - 4 && y <= pickerY + pickerW) {
            this.dragging = "picker";
            this.applyPointer(x, y);
        }
    }

    /** mousemove：拖拽中持续选色 */
    dragFromEvent(e) {
        if (!this.dragging) return;
        const { x, y } = this.eventPos(e);
        this.applyPointer(x, y);
    }

    /** 按拖拽类型把指针位置换算为 HSV 并应用（越界自动钳制） */
    applyPointer(x, y) {
        const { pickerX, pickerY, pickerW } = this.layout();
        if (this.dragging === "picker") {
            this.setHsv(
                this.hue,
                clamp((x - pickerX) / pickerW, 0, 1),
                clamp(1 - (y - pickerY) / pickerW, 0, 1),
            );
        } else {
            const hue = Math.round(clamp(((x - pickerX) / pickerW) * 360, 0, 360));
            if (hue !== this.hue) this.setHsv(hue, this.s, this.v);
        }
    }

    /** 全量重绘（dpr 缩放保证高分屏清晰） */
    redraw() {
        const { cssW, cssH, pickerX, pickerY, pickerW, hueY, infoY, btnY } = this.layout();
        const dpr = window.devicePixelRatio || 1;
        const pxW = Math.max(1, Math.round(cssW * dpr));
        const pxH = Math.max(1, Math.round(cssH * dpr));
        if (this.canvas.width !== pxW || this.canvas.height !== pxH) {
            this.canvas.width = pxW;
            this.canvas.height = pxH;
        }
        const ctx = this.ctx;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        this.drawPicker(ctx, pickerX, pickerY, pickerW);
        this.drawHueBar(ctx, pickerX, hueY, pickerW);
        this.drawInfo(ctx, pickerX, infoY, cssW - PAD * 2);
        this.drawButton(ctx, pickerX, btnY, cssW - PAD * 2);
    }

    /** 色域：当前色相下的饱和度×明度平面（离屏缓存复用） */
    getPickerCache(size) {
        const key = Math.round(size);
        if (this._pickerCache && this._pickerCache.__size === key && this._pickerCache.__hue === this.hue) {
            return this._pickerCache;
        }
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(2, key);
        canvas.height = Math.max(2, key);
        const cctx = canvas.getContext("2d");
        const img = cctx.createImageData(canvas.width, canvas.height);
        const data = img.data;
        for (let py = 0; py < canvas.height; py++) {
            const v = 1 - py / (canvas.height - 1);
            for (let px = 0; px < canvas.width; px++) {
                const s = px / (canvas.width - 1);
                const [r, g, b] = hsvToRgb(this.hue, s, v);
                const i = (py * canvas.width + px) * 4;
                data[i] = r;
                data[i + 1] = g;
                data[i + 2] = b;
                data[i + 3] = 255;
            }
        }
        cctx.putImageData(img, 0, 0);
        canvas.__size = key;
        canvas.__hue = this.hue;
        this._pickerCache = canvas;
        return canvas;
    }

    drawPicker(ctx, x, y, size) {
        ctx.drawImage(this.getPickerCache(size), x, y, size, size);
        // 边框
        ctx.strokeStyle = "rgba(120,120,120,0.5)";
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, size - 1, size - 1);
        // 选中标记：外白圈 + 内黑圈
        const mx = x + this.s * size;
        const my = y + (1 - this.v) * size;
        ctx.beginPath();
        ctx.arc(mx, my, 6, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(mx, my, 4.5, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(0,0,0,0.8)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    /** 色相渐变滑条（彩虹横条，按宽度离屏缓存） */
    drawHueBar(ctx, x, y, width) {
        const key = Math.max(2, Math.round(width));
        if (!this._hueCache || this._hueCache.__w !== key) {
            const canvas = document.createElement("canvas");
            canvas.width = key;
            canvas.height = 1;
            const cctx = canvas.getContext("2d");
            const img = cctx.createImageData(key, 1);
            const data = img.data;
            for (let px = 0; px < key; px++) {
                const [r, g, b] = hsvToRgb((px / (key - 1)) * 360, 1, 1);
                const i = px * 4;
                data[i] = r;
                data[i + 1] = g;
                data[i + 2] = b;
                data[i + 3] = 255;
            }
            cctx.putImageData(img, 0, 0);
            canvas.__w = key;
            this._hueCache = canvas;
        }
        ctx.drawImage(this._hueCache, x, y, width, HUE_H);
        ctx.strokeStyle = "rgba(120,120,120,0.5)";
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, width - 1, HUE_H - 1);
        // 色相指针
        const mx = x + (this.hue / 360) * width;
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.fillRect(mx - 2, y - 2, 4, HUE_H + 4);
        ctx.strokeStyle = "rgba(0,0,0,0.8)";
        ctx.lineWidth = 1;
        ctx.strokeRect(mx - 2.5, y - 2.5, 5, HUE_H + 5);
    }

    /** 预览行：醒目色块 + 颜色值文本 + 格式切换按钮（点击即刻切换 RGB/十六进制） */
    drawInfo(ctx, x, y, width) {
        const [r, g, b] = this.color;
        const swatchH = INFO_H - 10;
        // 色块（放大，双线边框更醒目）
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(x, y, SWATCH_W, swatchH);
        ctx.strokeStyle = "rgba(0,0,0,0.55)";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 0.75, y + 0.75, SWATCH_W - 1.5, swatchH - 1.5);
        ctx.strokeStyle = "rgba(255,255,255,0.35)";
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 3, y + 3, SWATCH_W - 6, swatchH - 6);
        // 颜色值文本（只读，格式跟随「颜色类型」参数）
        const text = this.colorText(this.isHexMode());
        const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        ctx.fillStyle = lum > 0.55 ? "#1c1c1c" : "#f0f0f0";
        ctx.font = "13px 'Consolas', monospace";
        ctx.textBaseline = "middle";
        ctx.fillText(text, x + SWATCH_W + 12, y + swatchH / 2);
        // 复制按钮
        const { copyBtnX, copyBtnY } = this.layout();
        this.drawCopyButton(ctx, copyBtnX, copyBtnY);
    }

    /** 复制按钮：显示"复制"，点击后短暂变绿并显示"✓ 已复制" */
    drawCopyButton(ctx, x, y) {
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, y, COPY_W, COPY_H, 5);
        else ctx.rect(x, y, COPY_W, COPY_H);
        ctx.fillStyle = this._copied
            ? "rgba(46,125,50,0.6)"
            : this._hoverCopy ? "rgba(115,115,145,0.55)" : "rgba(90,90,115,0.4)";
        ctx.fill();
        ctx.strokeStyle = this._copied ? "rgba(129,199,132,0.8)" : "rgba(150,150,175,0.5)";
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = "#eee";
        ctx.font = "bold 13px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(this._copied ? "✓ 已复制" : "复制", x + COPY_W / 2, y + COPY_H / 2 + 0.5);
        ctx.textAlign = "left";
    }

    /** 复制当前颜色值到剪贴板（格式跟随「颜色类型」参数），成功后短暂反馈 */
    copyColor() {
        const text = this.colorText(this.isHexMode());
        const done = () => {
            this._copied = true;
            this.redraw();
            setTimeout(() => {
                this._copied = false;
                this.redraw();
            }, 1200);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(() => this.fallbackCopy(text, done));
        } else {
            this.fallbackCopy(text, done);
        }
    }

    /** 剪贴板 API 不可用时的兜底：隐藏 textarea + execCommand */
    fallbackCopy(text, done) {
        try {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
            done();
        } catch {
            done();
        }
    }

    /** 当前是否为十六进制显示模式（跟随「颜色类型」参数） */
    isHexMode() {
        return this.node.widgets?.find((w) => w.name === "颜色类型")?.value === "十六进制";
    }

    /** 按模式格式化颜色值文本 */
    colorText(hexMode) {
        const [r, g, b] = this.color;
        return hexMode
            ? `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0").toUpperCase()).join("")}`
            : `${r},${g},${b}`;
    }

    /** 鼠标悬停：更新按钮高亮与光标 */
    updateHover(e) {
        const { cssW, pickerX, copyBtnX, copyBtnY, btnY, btnH } = this.layout();
        const { x, y } = this.eventPos(e);
        const overBtn = y >= btnY && y <= btnY + btnH && x >= pickerX && x <= cssW - PAD;
        const overCopy = y >= copyBtnY && y <= copyBtnY + COPY_H && x >= copyBtnX && x <= copyBtnX + COPY_W;
        if (overBtn !== this._hoverBtn || overCopy !== this._hoverCopy) {
            this._hoverBtn = overBtn;
            this._hoverCopy = overCopy;
            this.canvas.style.cursor = overBtn || overCopy ? "pointer" : "crosshair";
            this.redraw();
        }
    }

    /** 屏幕取色按钮：色相环图标 + 文字 */
    drawButton(ctx, x, y, width) {
        const h = BTN_H;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, y, width, h, 5);
        else ctx.rect(x, y, width, h);
        ctx.fillStyle = this._hoverBtn ? "rgba(115,115,145,0.5)" : "rgba(90,90,115,0.35)";
        ctx.fill();
        ctx.strokeStyle = "rgba(150,150,175,0.45)";
        ctx.lineWidth = 1;
        ctx.stroke();
        // 图标：色相环 + 中心当前色
        const cx = x + 22;
        const cy = y + h / 2;
        if (ctx.createConicGradient) {
            const grad = ctx.createConicGradient(0, cx, cy);
            for (let i = 0; i <= 12; i++) {
                const [rr, gg, bb] = hsvToRgb((i / 12) * 360, 1, 1);
                grad.addColorStop(i / 12, `rgb(${rr},${gg},${bb})`);
            }
            ctx.beginPath();
            ctx.arc(cx, cy, 7, 0, Math.PI * 2);
            ctx.fillStyle = grad;
            ctx.fill();
        } else {
            ctx.beginPath();
            ctx.arc(cx, cy, 7, 0, Math.PI * 2);
            ctx.fillStyle = `rgb(${this.color[0]},${this.color[1]},${this.color[2]})`;
            ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(cx, cy, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = `rgb(${this.color[0]},${this.color[1]},${this.color[2]})`;
        ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.4)";
        ctx.lineWidth = 1;
        ctx.stroke();
        // 文字
        ctx.fillStyle = "#ddd";
        ctx.font = "13px sans-serif";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText("屏幕取色", cx + 14, cy + 0.5);
    }

    /** 打开系统取色器：优先 EyeDropper（屏幕任意位置取色），不可用时回退原生颜色选择器 */
    async openScreenPicker() {
        if (typeof EyeDropper !== "undefined") {
            try {
                const result = await new EyeDropper().open();
                if (result?.sRGBHex) this.applyColor(result.sRGBHex);
            } catch (e) {
                // 用户按 ESC 取消，忽略
            }
            return;
        }
        const input = document.createElement("input");
        input.type = "color";
        input.value = this.toHex();
        const onChange = () => this.applyColor(input.value);
        input.addEventListener("input", onChange);
        input.addEventListener("change", onChange);
        input.click();
    }

    /** 当前颜色 → "#RRGGBB" */
    toHex() {
        const [r, g, b] = this.color;
        return `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0").toUpperCase()).join("")}`;
    }
}

app.registerExtension({
    name: "SHOUWANG.ColorPicker",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：隐藏「颜色值」输入框，添加取色器 DOM widget ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            setTimeout(() => {
                // 隐藏「颜色值」输入框（选色结果自动写入，执行时传给后端）
                const colorWidget = this.widgets?.find((w) => w.name === "颜色值");
                if (colorWidget?.element) colorWidget.element.style.display = "none";

                // 添加取色器 DOM widget
                const picker = new ColorPickerWidget(this);
                this.colorPickerWidget = picker;
                this.addDOMWidget("取色器", "custom", picker.canvas, {
                    getHeight: () => picker.getHeight(),
                    serialize: false, // 不参与 prompt/widgets 序列化（颜色经「颜色值」widget 传递）
                });

                // 从已保存的「颜色值」初始化取色器显示
                picker.applyColor(colorWidget?.value);
                picker.redraw();

                // 「颜色类型」切换 → 刷新预览文本格式
                const typeWidget = this.widgets?.find((w) => w.name === "颜色类型");
                if (typeWidget && !typeWidget.__swCpBound) {
                    typeWidget.__swCpBound = true;
                    typeWidget.callback = () => picker.redraw();
                }
                // 「颜色值」被外部修改（如导入工作流）→ 同步取色器
                if (colorWidget && !colorWidget.__swCpBound) {
                    colorWidget.__swCpBound = true;
                    colorWidget.callback = () => picker.applyColor(colorWidget.value);
                }

                // 初始尺寸：340 宽，高度按方形色域计算
                const initWidth = 340;
                this.setSize([initWidth, PAD + (initWidth - 16) + GAP + HUE_H + GAP + INFO_H + GAP + BTN_H + PAD]);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        // ── 执行完成：「随机颜色」模式下后端回传实际颜色 → 同步取色器显示 ──
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const color = message?.color?.[0];
            if (color) this.colorPickerWidget?.applyColor(color);
        };
    },
});
