/**
 * ComfyUI-SHOUWANG-ToolBox — 守望-加载图像前端扩展
 *
 * 为节点添加「复制 / 粘贴」按钮：复制当前选中图片到系统剪贴板；
 * 粘贴读取剪贴板图片 → 上传到 input 文件夹并自动选中加载（等效「保存 + 上传 + 选择」一步完成）。
 *
 * 图片预览采用画布绘制 widget（与「守望-预览任何」同一套机制）：
 *   - 占用 ComfyUI 原生 $$canvas-image-preview 名称，绘制循环判定「预览已存在」不再叠加原生预览；
 *   - 图片按 contain 适配绘制在节点剩余区域，拖动四角缩放时跟随缩放；
 *   - 预览区固定最小高度，不被图片比例撑大，节点高度可自由调整。
 *
 * 按钮为画布绘制 widget：规避新版 ComfyUI addDOMWidget 的 position:fixed 定位
 * 在画布缩放/平移时错位漂移的问题；宽度随节点宽度自适应（封顶 BTN_MAX_WIDTH，保底 BTN_MIN_WIDTH）。
 *
 * 剪贴板兼容性：依赖 Clipboard API（安全上下文），本地 127.0.0.1 访问可用；
 * 非安全上下文（如局域网 IP 访问）下按钮会提示剪贴板不可用。
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_TYPE = "ShouWangLoadImage";
const DEFAULT_SIZE = [360, 220]; // 节点默认画布尺寸（宽 x 高，加载工作流时 configure 会恢复保存的尺寸）
const BTN_ROW_HEIGHT = 36; // 按钮行兜底高度（容器 padding + 按钮高度）
const BTN_HEIGHT = 28; // 按钮固定高度
const BTN_GAP = 6; // 按钮间距
const BTN_PAD = 4; // 按钮容器左右内边距
const BTN_MAX_WIDTH = 128; // 按钮最大宽度
const BTN_MIN_WIDTH = 48; // 按钮最小宽度（节点缩窄时的兜底）
const IMG_MIN_HEIGHT = 60; // 图片展示区最小高度
const CANVAS_PREVIEW_WIDGET = "$$canvas-image-preview"; // ComfyUI 原生 canvas 预览 widget 名（自定义预览占用此名，原生机制判定「预览已存在」不再重复添加）

/**
 * 生成时间戳文件名（秒级精度，避免重名覆盖）：
 * clipboard_20260814_153000.png
 */
function makeFileName(ext) {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
    return `clipboard_${stamp}.${ext}`;
}

/** 由文件名构造预览 URL（type=input，与原生 LoadImage 一致） */
const previewUrl = (name) => api.apiURL(
    `/view?filename=${encodeURIComponent(name)}&type=input&subfolder=${app.getRandParam() ?? ""}`,
);

let lastCopiedName = null; // 复制时记录的原文件名：粘贴时按原名上传，外部复制（无记录）时回退时间戳命名
let lastCopiedDigest = null; // 复制图片的内容指纹：校验剪贴板仍是同一张图才沿用原名，防止误覆盖原文件

/**
 * 计算 Blob 内容的 SHA-256 指纹（依赖安全上下文，与 Clipboard API 一致）
 */
async function hashBlob(blob) {
    const buf = await blob.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * 读取剪贴板中的第一张图片
 * @returns {Promise<{blob: Blob, ext: string}|null>} 剪贴板无图片返回 null
 */
async function readClipboardImage() {
    if (!navigator.clipboard?.read) return null;
    const items = await navigator.clipboard.read();
    for (const item of items) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (!type) continue;
        const ext = type === "image/jpeg" ? "jpg" : type.split("/")[1];
        const blob = await item.getType(type);
        return { blob, ext };
    }
    return null;
}

/**
 * 上传图片到 input 文件夹（复用 ComfyUI 原生 /upload/image 接口）
 * @returns {Promise<string>} 实际保存的文件名
 */
async function uploadToInput(blob, filename) {
    const form = new FormData();
    form.append("image", new File([blob], filename, { type: blob.type }), filename);
    form.append("type", "input");
    const resp = await fetch("/upload/image", { method: "POST", body: form });
    if (!resp.ok) throw new Error("上传失败");
    const data = await resp.json();
    return data.name;
}

/**
 * 把图片 widget 切换到指定文件：更新选项列表、选中新值并刷新预览
 */
function selectImage(node, name) {
    const widget = node.widgets?.find((w) => w.name === "image");
    if (!widget) return;
    // 选项列表补入新文件并排序（与后端 sorted(files) 保持一致）
    const values = [...(widget.options?.values ?? [])];
    if (!values.includes(name)) values.push(name);
    values.sort();
    widget.options.values = values;
    widget.value = name;
    // 预览刷新：value 变化会经 callback 链触发；同名时手动兜底刷新一次
    updatePreview(node);
}

/**
 * 把节点当前选中的图片写入系统剪贴板（统一经 canvas 转 png，保证任意格式可粘贴）
 */
async function copyImageToClipboard(node) {
    const widget = node.widgets?.find((w) => w.name === "image");
    const name = widget?.value;
    if (!name) throw new Error("未选择图片");
    // 记录原文件名（去掉可能的子目录前缀），粘贴时按原名上传
    lastCopiedName = name.split("/").pop();
    const resp = await fetch(`/view?filename=${encodeURIComponent(name)}&type=input&subfolder=`);
    if (!resp.ok) throw new Error("读取图片失败");
    const blob = await resp.blob();
    // 浏览器自动识别真实格式后转 png，ClipboardItem 声明 image/png 才能稳定写入
    let bmp;
    try {
        bmp = await createImageBitmap(blob);
    } catch (e) {
        throw new Error("图片解码失败");
    }
    const canvas = document.createElement("canvas");
    canvas.width = bmp.width;
    canvas.height = bmp.height;
    canvas.getContext("2d").drawImage(bmp, 0, 0);
    const pngBlob = await new Promise((res) => canvas.toBlob(res, "image/png"));
    if (!pngBlob) throw new Error("图片转换失败");
    // 记录内容指纹：粘贴时校验剪贴板仍是同一张图才沿用原名
    lastCopiedDigest = await hashBlob(pngBlob);
    if (!navigator.clipboard?.write) throw new Error("剪贴板不可用");
    await navigator.clipboard.write([new ClipboardItem({ "image/png": pngBlob })]);
}

/**
 * 粘贴：读取剪贴板图片 → 上传 input 目录 → 自动选中加载。
 * 校验剪贴板仍是复制时那张图才用原名；否则（外部复制）用时间戳命名，避免误覆盖原文件。
 */
async function pasteFromClipboard(node) {
    let img;
    try {
        img = await readClipboardImage();
    } catch (e) {
        throw new Error("剪贴板不可用");
    }
    if (!img) throw new Error("剪贴板无图片");
    const useName = lastCopiedName && (await hashBlob(img.blob)) === lastCopiedDigest
        ? lastCopiedName
        : makeFileName(img.ext);
    const name = await uploadToInput(img.blob, useName);
    selectImage(node, name);
}

/**
 * 图片预览画布 widget：在节点画布上绘制图片，并随节点尺寸缩放。
 * draw 使用节点剩余可用区域（节点宽 × 节点高扣除上方 widget 后的剩余高度），
 * 按 contain 比例适配居中绘制；拖动四角缩放节点时图片同步跟随缩放。
 * computeSize 只返回固定最小高度，不按图片比例撑大节点，用户可自由调整节点高度。
 * 名称占用 $$canvas-image-preview：ComfyUI 绘制循环 find 到同名 widget 后不会再添加原生预览。
 */
class ImagePreviewWidget {
    constructor(node) {
        this.name = CANVAS_PREVIEW_WIDGET; // 占用原生预览名：绘制循环 find 到它后不会再加原生预览 widget
        this.type = "custom";
        this.__swCustom = true; // 自定义预览标记：清理原生遗留时跳过
        this.node = node;
        this.serialize = false; // 预览图不参与序列化（每次重建后按 image widget 值重新加载）
        this.img = null;
        this.src = null;
    }

    /** 加载新图片：同名且已加载完成时跳过重复加载 */
    setImage(src) {
        if (src === this.src && this.img?.naturalWidth) {
            this.node.graph?.setDirtyCanvas(true, true);
            return;
        }
        this.src = src;
        this.img = null;
        if (!src) {
            this.node.graph?.setDirtyCanvas(true, true);
            return;
        }
        const img = new Image();
        img.onload = () => {
            if (this.src === src) this.img = img;
            this.node.graph?.setDirtyCanvas(true, true);
        };
        img.onerror = () => {
            if (this.src === src) this.img = null;
            this.node.graph?.setDirtyCanvas(true, true);
        };
        img.src = src;
    }

    /** 布局最小高度：固定最小值，避免节点被图片比例撑到无法手动缩小 */
    computeSize(width) {
        return [width || this.node.size?.[0] || 200, IMG_MIN_HEIGHT];
    }

    draw(ctx, node, width, y) {
        const [nodeWidth, nodeHeight] = node.size;
        // 参考原生 ImagePreview：设置「Comfy.Node.AllowImageSizeDraw」开启时，
        // 在图片下方绘制 “宽 × 高”，底部预留 15px 文字空间
        const showSize = !!app.ui?.settings?.getSettingValue?.("Comfy.Node.AllowImageSizeDraw");
        const availH = Math.max(IMG_MIN_HEIGHT, nodeHeight - y - (showSize ? 15 : 0));
        if (!this.img?.naturalWidth) return;
        // contain 适配：图片不超出节点宽高，居中绘制
        const scale = Math.min(nodeWidth / this.img.naturalWidth, availH / this.img.naturalHeight);
        const dw = this.img.naturalWidth * scale;
        const dh = this.img.naturalHeight * scale;
        const dx = (nodeWidth - dw) / 2;
        const dy = y + (availH - dh) / 2;
        ctx.drawImage(this.img, dx, dy, dw, dh);
        // 与原生一致：在图片下方 10px 处居中绘制当前分辨率
        if (showSize) {
            ctx.fillStyle = LiteGraph.NODE_TEXT_COLOR;
            ctx.textAlign = "center";
            ctx.font = "10px sans-serif";
            ctx.fillText(
                `${Math.round(this.img.naturalWidth)} × ${Math.round(this.img.naturalHeight)}`,
                dx + dw / 2,
                dy + dh + 10,
            );
        }
    }
}

/**
 * 刷新节点图片预览：确保自定义预览 widget 存在（顺带清理原生遗留），
 * 并按 image widget 当前值加载图片。幂等，可安全地在 callback / selectImage / configure 中重复调用。
 */
function updatePreview(node) {
    const name = node.widgets?.find((w) => w.name === "image")?.value;
    let preview = node.widgets?.find((w) => w.name === CANVAS_PREVIEW_WIDGET && w.__swCustom);
    if (!preview) {
        // 清理 ComfyUI 原生遗留的 canvas 预览 widget（无 __swCustom 标记）
        if (node.widgets) {
            for (let i = node.widgets.length - 1; i >= 0; i--) {
                const w = node.widgets[i];
                if (w.name === CANVAS_PREVIEW_WIDGET && !w.__swCustom) {
                    w.onRemove?.();
                    node.widgets.splice(i, 1);
                }
            }
        }
        preview = new ImagePreviewWidget(node);
        // 插入到「复制粘贴」按钮行之后，保证按钮行始终在图片预览上方
        // （onConfigure 恢复时可能先于按钮行创建，不能直接追加到末尾）
        const rowIdx = node.widgets?.findIndex((w) => w.name === "复制粘贴") ?? -1;
        if (rowIdx > -1) node.widgets.splice(rowIdx + 1, 0, preview);
        else node.addCustomWidget(preview);
    }
    preview.setImage(name ? previewUrl(name) : null);
    node.setDirtyCanvas(true, true);
}

/**
 * 复制/粘贴按钮行画布 widget：直接在节点画布上绘制按钮并响应点击，
 * 规避新版 ComfyUI 中 addDOMWidget 的 fixed 定位容器在画布平移/缩放后错位（按钮脱离节点）的问题。
 * 按钮宽度随节点宽度自适应（封顶 BTN_MAX_WIDTH，保底 BTN_MIN_WIDTH），点击后短暂显示反馈文案。
 */
class CanvasButtonRowWidget {
    constructor(node, buttons) {
        this.name = "复制粘贴";
        this.type = "custom";
        this.node = node;
        this.serialize = false; // 按钮不参与序列化（图片选择经「image」widget 传递）
        this.buttons = buttons;
        this.states = buttons.map((b) => ({ label: b.label, disabled: false }));
    }

    computeSize(width) {
        return [width || this.node.size?.[0] || 200, BTN_ROW_HEIGHT];
    }

    /** 第 i 个按钮当前绘制区域（相对节点左上角）：[x, y, w, h] */
    getBounds(i) {
        const nodeWidth = this.node.size?.[0] || 200;
        const avail = Math.max(BTN_MIN_WIDTH * 2 + BTN_GAP + BTN_PAD * 2, nodeWidth - BTN_PAD * 2);
        const btnW = Math.min(BTN_MAX_WIDTH, Math.floor((avail - BTN_GAP) / 2));
        const x = (nodeWidth - (btnW * 2 + BTN_GAP)) / 2 + i * (btnW + BTN_GAP);
        const y = (this.y ?? 0) + (BTN_ROW_HEIGHT - BTN_HEIGHT) / 2;
        return [x, y, btnW, BTN_HEIGHT];
    }

    draw(ctx, node, width, y) {
        for (let i = 0; i < this.buttons.length; i++) {
            const [x, by, btnW, btnH] = this.getBounds(i);
            const st = this.states[i];
            ctx.fillStyle = st.disabled ? "#2a2a2a" : "#222";
            ctx.strokeStyle = "#444";
            ctx.lineWidth = 1;
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(x, by, btnW, btnH, 4);
            else ctx.rect(x, by, btnW, btnH);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = "#ddd";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(st.label, x + btnW / 2, by + btnH / 2 + 1);
        }
    }

    mouse(event, pos) {
        if (event.type !== "pointerdown") return false;
        for (let i = 0; i < this.buttons.length; i++) {
            if (this.states[i].disabled) continue;
            const [x, by, btnW, btnH] = this.getBounds(i);
            if (pos[0] < x || pos[0] > x + btnW || pos[1] < by || pos[1] > by + btnH) continue;
            event.preventDefault?.();
            this.click(i);
            return true; // 已处理，阻止画布其他行为
        }
        return false;
    }

    /** 执行第 i 个按钮的操作并短暂显示反馈文案 */
    async click(i) {
        const st = this.states[i];
        const b = this.buttons[i];
        st.disabled = true;
        try {
            await b.onClick();
            st.label = b.feedback;
        } catch (e) {
            st.label = e?.message?.length <= 8 ? e.message : "操作失败";
        }
        setTimeout(() => {
            st.label = b.label;
            st.disabled = false;
            this.node.graph?.setDirtyCanvas(true, true);
        }, 1200);
        this.node.graph?.setDirtyCanvas(true, true);
    }
}

app.registerExtension({
    name: "SHOUWANG.LoadImage",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 仅处理目标节点
        if (nodeData.name !== NODE_TYPE) return;

        // 新建节点固定默认尺寸：覆盖 computeSize 钳制自动尺寸计算，
        // 任何内部 setSize(computeSize()) 都得到 360x220，杜绝新建后被自动计算覆盖。
        // 注意：仅当节点既未被用户手动缩放、也未被 configure（加载工作流/ctrl+z 撤回）恢复时钳制；
        // 否则尊重实际尺寸，避免撤回后跳回默认宽高导致布局混乱
        const baseComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function () {
            if (!this.__userResized && !this.__configured) return [...DEFAULT_SIZE];
            return baseComputeSize.apply(this, arguments);
        };

        // configure 恢复（加载工作流 / ctrl+z 撤回）：标记已从序列化恢复尺寸，
        // 此后不再强制默认尺寸，与普通节点行为一致；同时按恢复的 image 值刷新预览
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            if (info?.size) this.__configured = true;
            updatePreview(this);
        };

        // ── 节点创建：包装 image 切换回调、添加「复制/粘贴」按钮行与自定义图片预览 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 同步先设一次默认尺寸（image widget 创建前的初始值）
            this.setSize([...DEFAULT_SIZE]);

            setTimeout(() => {
                // 已添加过则跳过（避免工作流重复加载时重复创建）
                if (this.widgets?.some((w) => w.name === "复制粘贴")) return;

                // 节点已从序列化恢复（加载工作流/ctrl+z 撤回）：不再强制默认尺寸，
                // 保持 configure 恢复的保存尺寸，避免覆盖导致布局跳变
                const restored = this.__configured;
                if (!restored) this.setSize([...DEFAULT_SIZE]);

                // 包装 image widget 回调：切换图片时刷新自定义预览。
                // 原回调（ComfyUI 内置 setNodeOutputs）必须保留，执行输出依赖它
                const imageWidget = this.widgets?.find((w) => w.name === "image");
                if (imageWidget && !imageWidget.__swWrapped) {
                    const origCb = imageWidget.callback;
                    imageWidget.__swWrapped = true;
                    imageWidget.callback = function (value) {
                        const r = origCb?.apply(this, arguments);
                        updatePreview(this.node);
                        return r;
                    };
                }

                // 复制：把当前选中的图片写入系统剪贴板
                const copyBtn = { label: "复制", feedback: "已复制", onClick: () => copyImageToClipboard(this) };
                // 粘贴：读取剪贴板图片 → 上传 input 目录 → 自动选中加载
                const pasteBtn = { label: "粘贴", feedback: "已粘贴", onClick: () => pasteFromClipboard(this) };

                this.addCustomWidget(new CanvasButtonRowWidget(this, [copyBtn, pasteBtn]));
                // 按钮行移到预览 widget 之前（onConfigure 恢复时预览可能已先创建）
                const pvIdx = this.widgets?.findIndex((w) => w.__swCustom) ?? -1;
                if (pvIdx > -1 && pvIdx < this.widgets.length - 1) {
                    const btnRow = this.widgets.splice(this.widgets.length - 1, 1)[0];
                    this.widgets.splice(pvIdx, 0, btnRow);
                }

                // 自定义图片预览（名称占用 $$canvas-image-preview，阻止原生预览叠加）
                updatePreview(this);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        // ── 节点缩放：图片预览随节点尺寸重绘（按钮为画布 widget，宽度自动适配） ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            // 仅当尺寸实际变化时才解锁固定默认尺寸（用户拖动）；
            // 内部 setSize 传入相同尺寸或 configure 恢复时不误解锁
            const changed = !!this.__lastSize && !!size &&
                (size[0] !== this.__lastSize[0] || size[1] !== this.__lastSize[1]);
            this.__lastSize = size ? [size[0], size[1]] : null;
            if (changed) this.__userResized = true;
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
