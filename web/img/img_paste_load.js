/**
 * ComfyUI-SHOUWANG-ToolBox — 守望-加载图像前端扩展
 *
 * 为节点添加「粘贴」按钮：点击后读取系统剪贴板中的图片，
 * 直接上传到 input 文件夹并自动选中加载，等效于「保存文件 + 上传 + 选择」一步完成。
 *
 * 剪贴板兼容性：依赖 Clipboard API（安全上下文），本地 127.0.0.1 访问可用；
 * 非安全上下文（如局域网 IP 访问）下按钮会提示剪贴板不可用。
 */

import { app } from "../../../scripts/app.js";

const NODE_TYPE = "ShouWangLoadImage";
const DEFAULT_SIZE = [360, 220]; // 节点默认画布尺寸（宽 x 高，加载工作流时 configure 会恢复保存的尺寸）
const BTN_ROW_HEIGHT = 36; // 按钮行兜底高度（容器 padding + 按钮高度）
const BTN_HEIGHT = 28; // 按钮固定高度
const BTN_GAP = 6; // 按钮间距
const BTN_PAD = 4; // 按钮容器左右内边距
const BTN_MAX_WIDTH = 128; // 按钮最大宽度
const BTN_MIN_WIDTH = 48; // 按钮最小宽度（节点缩窄时的兜底）

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
    // 刷新图片预览（/view 路由，与原生 LoadImage 一致）
    const url = `/view?filename=${encodeURIComponent(name)}&type=input&subfolder=`;
    const img = new Image();
    img.src = url;
    node.imgs = [img];
    widget.callback?.(widget.value);
    node.setDirtyCanvas(true, true);
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
 * 按节点宽度同步按钮宽度：两按钮并排总宽不超出节点内容宽度
 * 节点越宽按钮越宽（封顶 BTN_MAX_WIDTH），节点缩窄时按钮同步收窄（保底 BTN_MIN_WIDTH）
 */
const syncButtonWidth = (node, copyBtn, pasteBtn) => {
    const nodeWidth = node.size?.[0] ?? 200;
    const avail = Math.max(BTN_MIN_WIDTH * 2 + BTN_GAP + BTN_PAD * 2, nodeWidth - BTN_PAD * 2);
    const btnWidth = Math.min(BTN_MAX_WIDTH, Math.floor((avail - BTN_GAP) / 2));
    copyBtn.style.width = `${btnWidth}px`;
    pasteBtn.style.width = `${btnWidth}px`;
};

/**
 * 创建带点击反馈的按钮：点击后短暂显示反馈文案，1.2s 后恢复
 */
function createButton(label, feedbackLabel, onClick) {
    const btn = document.createElement("button");
    btn.textContent = label;
    // 宽度不在此固定：由 syncButtonWidth 按节点宽度动态计算，避免按钮脱离节点
    btn.style.cssText = `
        height: ${BTN_HEIGHT}px;
        flex: none;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        font-size: 12px;
        line-height: 1;
        color: var(--fg-color, #ddd);
        background: var(--comfy-input-bg, #222);
        border: 1px solid var(--border-color, #444);
        border-radius: 4px;
        cursor: pointer;
        user-select: none;
    `;
    btn.addEventListener("mouseenter", () => {
        btn.style.background = "var(--comfy-input-bg, #333)";
    });
    btn.addEventListener("mouseleave", () => {
        btn.style.background = "var(--comfy-input-bg, #222)";
    });
    btn.addEventListener("click", async () => {
        if (btn.disabled) return;
        btn.disabled = true;
        try {
            await onClick();
            btn.textContent = feedbackLabel;
        } catch (e) {
            btn.textContent = e?.message?.length <= 8 ? e.message : "操作失败";
        }
        setTimeout(() => {
            btn.textContent = label;
            btn.disabled = false;
        }, 1200);
    });
    return btn;
}

app.registerExtension({
    name: "SHOUWANG.LoadImage",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 仅处理目标节点
        if (nodeData.name !== NODE_TYPE) return;

        // 新建节点固定默认尺寸：覆盖 computeSize 钳制自动尺寸计算，
        // 任何内部 setSize(computeSize()) 都得到 360x220，杜绝新建后被自动计算覆盖
        const baseComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function () {
            if (!this.__userResized) return [...DEFAULT_SIZE];
            return baseComputeSize.apply(this, arguments);
        };

        // ── 节点创建：添加「粘贴」按钮 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 同步先设一次默认尺寸（image widget 创建前的初始值）
            this.setSize([...DEFAULT_SIZE]);

            setTimeout(() => {
                // 已添加过则跳过（避免工作流重复加载时重复创建）
                if (this.widgets?.some((w) => w.name === "复制粘贴")) return;

                const el = document.createElement("div");
                el.style.cssText = `display:flex;justify-content:center;gap:${BTN_GAP}px;padding:${BTN_PAD}px;`;

                // 复制：把当前选中的图片写入系统剪贴板
                const copyBtn = createButton("复制", "已复制", () => copyImageToClipboard(this));

                // 粘贴：读取剪贴板图片 → 上传 input 目录 → 自动选中加载
                const pasteBtn = createButton("粘贴", "已粘贴", async () => {
                    let img;
                    try {
                        img = await readClipboardImage();
                    } catch (e) {
                        throw new Error("剪贴板不可用");
                    }
                    if (!img) throw new Error("剪贴板无图片");
                    // 校验剪贴板仍是复制时那张图才用原名；否则（外部复制）用时间戳命名，避免误覆盖原文件
                    const useName = lastCopiedName && (await hashBlob(img.blob)) === lastCopiedDigest
                        ? lastCopiedName
                        : makeFileName(img.ext);
                    const name = await uploadToInput(img.blob, useName);
                    selectImage(this, name);
                });

                el.appendChild(copyBtn);
                el.appendChild(pasteBtn);

                // 保存按钮引用：节点缩放时按节点宽度同步按钮宽度
                this.__copyPasteBtns = { copyBtn, pasteBtn };

                this.addDOMWidget("复制粘贴", "custom", el, {
                    getHeight: () => el.offsetHeight || BTN_ROW_HEIGHT,
                    serialize: false, // 按钮组不参与序列化（图片选择经「image」widget 传递）
                });
                // 按钮组加入后再设一次默认尺寸（widget 集合变化后）
                this.setSize([...DEFAULT_SIZE]);
                syncButtonWidth(this, copyBtn, pasteBtn);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        // ── 节点缩放：同步按钮宽度，与节点宽度联动 ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            this.__userResized = true; // 用户已手动调整尺寸：解锁固定默认尺寸，恢复系统计算
            const btns = this.__copyPasteBtns;
            if (btns) syncButtonWidth(this, btns.copyBtn, btns.pasteBtn);
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
