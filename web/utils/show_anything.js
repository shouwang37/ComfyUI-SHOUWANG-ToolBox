/**
 * ComfyUI-SHOUWANG-ToolBox — 展示任何节点前端扩展
 *
 * 执行后把后端返回的内容渲染到节点上：
 *   - 文本列表 → 渲染为只读多行输入框（参考 Easy-Use showAnything）
 *   - 图像列表 → 在节点画布上直接绘制图片，拖动四角缩放节点时图片跟随缩放（contain 适配）
 *   - 输入参数区提供「复制」按钮：点击后复制节点当前展示的全部文本内容
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

const NODE_TYPE = "ShouWangShowAnything";
const BTN_ROW_HEIGHT = 36; // 按钮行兜底高度（容器 padding + 按钮高度）
const BTN_HEIGHT = 28; // 按钮固定高度
const BTN_PAD = 4; // 按钮容器左右内边距
const BTN_MAX_WIDTH = 128; // 按钮最大宽度
const BTN_MIN_WIDTH = 48; // 按钮最小宽度（节点缩窄时的兜底）
const TITLE_HEIGHT = 30; // 节点标题栏高度（估算，用于计算图片可用高度）
const IMG_MIN_HEIGHT = 60; // 图片展示区最小高度
const CANVAS_PREVIEW_WIDGET = "$$canvas-image-preview"; // ComfyUI 原生 canvas 预览 widget 名（自定义预览占用此名，原生机制判定"预览已存在"不再重复添加）

/** 由后端返回的图像数据构造预览 URL */
const imageDataToUrl = (data) => api.apiURL(
    `/view?filename=${encodeURIComponent(data.filename)}&type=${data.type}&subfolder=${data.subfolder}${app.getPreviewFormatParam()}${app.getRandParam()}`,
);

/**
 * 图片预览画布 widget：在节点画布上绘制图片，并随节点尺寸缩放。
 * draw 使用节点剩余可用区域（节点宽 × 节点高扣除上方 widget 后的剩余高度），
 * 按 contain 比例适配居中绘制；拖动四角缩放节点时图片同步跟随缩放。
 * computeSize 只返回固定最小高度：节点尺寸始终由用户排版决定，
 * 执行后图片在剩余空间 contain 适配，不自动撑开也不压缩节点。
 */
class ImagePreviewWidget {
    constructor(node, images) {
        this.name = CANVAS_PREVIEW_WIDGET; // 占用原生预览名：绘制循环 find 到它后不会再加原生预览 widget
        this.type = "custom";
        this.__swCustom = true; // 自定义预览标记：onExecuted 清理原生遗留时跳过
        this.node = node;
        this.serialize = false; // 预览图不参与序列化（每次执行后重新渲染）
        this.images = images.map((d) => {
            const img = new Image();
            img.onload = () => {
                node.graph?.setDirtyCanvas(true, true);
            };
            img.src = imageDataToUrl(d);
            return { ...d, img };
        });
    }

    /** 布局最小高度：固定最小值，节点尺寸始终由用户控制，图片在剩余空间 contain 适配 */
    computeSize(width) {
        return [width || this.node.size?.[0] || 200, IMG_MIN_HEIGHT];
    }

    draw(ctx, node, width, y) {
        const [nodeWidth, nodeHeight] = node.size;
        // 参考原生 ImagePreview：设置「Comfy.Node.AllowImageSizeDraw」开启时，
        // 在图片下方绘制 “宽 × 高”，底部预留 15px 文字空间
        const showSize = !!app.ui?.settings?.getSettingValue?.("Comfy.Node.AllowImageSizeDraw");
        const availH = Math.max(IMG_MIN_HEIGHT, nodeHeight - y - (showSize ? 15 : 0));
        const images = this.images.filter((d) => d.img?.naturalWidth);
        if (!images.length) return;

        // 多张图片竖排均分高度，每张 contain 适配居中
        const slotH = availH / images.length;
        for (let i = 0; i < images.length; i++) {
            const img = images[i].img;
            const scale = Math.min(nodeWidth / img.naturalWidth, slotH / img.naturalHeight);
            const dw = img.naturalWidth * scale;
            const dh = img.naturalHeight * scale;
            const dx = (nodeWidth - dw) / 2;
            const dy = y + slotH * i + (slotH - dh) / 2;
            ctx.drawImage(img, dx, dy, dw, dh);
            // 与原生一致：单图时在图片下方 10px 处居中绘制当前分辨率
            if (showSize && images.length === 1) {
                ctx.fillStyle = LiteGraph.NODE_TEXT_COLOR;
                ctx.textAlign = "center";
                ctx.font = "10px sans-serif";
                ctx.fillText(
                    `${Math.round(img.naturalWidth)} × ${Math.round(img.naturalHeight)}`,
                    dx + dw / 2,
                    dy + dh + 10,
                );
            }
        }
    }
}

/**
 * 写入系统剪贴板：优先 Clipboard API，不可用时回退临时 textarea + execCommand
 */
async function copyToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
    document.body.appendChild(ta);
    ta.select();
    if (!document.execCommand("copy")) throw new Error("复制失败");
    document.body.removeChild(ta);
}

/**
 * 复制按钮画布 widget：直接在节点画布上绘制按钮并响应点击，
 * 规避新版 ComfyUI 中 addDOMWidget 的 fixed 定位容器在画布平移/缩放后错位（按钮脱离节点、叠在图片上方）的问题。
 * 按钮宽度随节点宽度自适应（封顶 BTN_MAX_WIDTH，保底 BTN_MIN_WIDTH），点击后短暂显示反馈文案。
 */
class CopyButtonWidget {
    constructor(node, onCopy) {
        this.name = "复制粘贴";
        this.type = "custom";
        this.node = node;
        this.onCopy = onCopy;
        this.serialize = false; // 按钮不参与序列化（展示内容经「text」widget 传递）
        this.label = "复制";
        this.disabled = false;
    }

    computeSize(width) {
        return [width || this.node.size?.[0] || 200, BTN_ROW_HEIGHT];
    }

    /** 当前按钮绘制区域（相对节点左上角）：[x, y, w, h] */
    getBounds() {
        const nodeWidth = this.node.size?.[0] || 200;
        const btnW = Math.min(BTN_MAX_WIDTH, Math.max(BTN_MIN_WIDTH, nodeWidth - BTN_PAD * 2));
        const x = (nodeWidth - btnW) / 2;
        const y = (this.y ?? 0) + (BTN_ROW_HEIGHT - BTN_HEIGHT) / 2;
        return [x, y, btnW, BTN_HEIGHT];
    }

    draw(ctx, node, width, y) {
        const [x, by, btnW, btnH] = this.getBounds();
        ctx.fillStyle = this.disabled ? "#2a2a2a" : "#222";
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
        ctx.fillText(this.label, x + btnW / 2, by + btnH / 2 + 1);
    }

    mouse(event, pos) {
        if (event.type !== "pointerdown" || this.disabled) return false;
        const [x, by, btnW, btnH] = this.getBounds();
        if (pos[0] < x || pos[0] > x + btnW || pos[1] < by || pos[1] > by + btnH) return false;
        event.preventDefault?.();
        this.click();
        return true; // 已处理，阻止画布其他行为
    }

    /** 执行复制并短暂显示反馈文案 */
    async click() {
        this.disabled = true;
        try {
            await this.onCopy();
            this.label = "已复制";
        } catch (e) {
            this.label = e?.message?.length <= 8 ? e.message : "操作失败";
        }
        setTimeout(() => {
            this.label = "复制";
            this.disabled = false;
            this.node.graph?.setDirtyCanvas(true, true);
        }, 1200);
        this.node.graph?.setDirtyCanvas(true, true);
    }
}

app.registerExtension({
    name: "SHOUWANG.ShowAnything",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：添加「复制」按钮画布 widget（不强制固定尺寸，执行后按内容自动撑开） ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            setTimeout(() => {
                // 已添加过则跳过（避免工作流重复加载时重复创建）
                if (this.widgets?.some((w) => w.name === "复制粘贴")) return;

                // 复制：把节点当前展示的全部文本内容写入系统剪贴板
                const btn = new CopyButtonWidget(this, async () => {
                    const texts = this.widgets
                        ?.filter((w) => w.name === "text")
                        .map((w) => w.value ?? "")
                        .filter((t) => t !== "");
                    if (!texts?.length) throw new Error("内容为空");
                    await copyToClipboard(texts.join("\n"));
                });
                this.addCustomWidget(btn);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        const onExecuted = nodeType.prototype.onExecuted;

        // 执行后：渲染后端返回内容（文本 → 只读多行输入框；图像 → 画布绘制预览）
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const texts = message?.text ?? [];
            const images = message?.images ?? [];

            // 清理 ComfyUI 原生遗留的 canvas 预览 widget（带 __swCustom 标记的自定义预览保留）
            if (this.widgets) {
                for (let i = this.widgets.length - 1; i >= 0; i--) {
                    const w = this.widgets[i];
                    if (w.name === CANVAS_PREVIEW_WIDGET && !w.__swCustom) {
                        w.onRemove?.();
                        this.widgets.splice(i, 1);
                    }
                }
            }

            // 移除上一次的图片预览 widget（本次可能切换为文本展示）
            if (this.__swImageWidget) {
                this.removeWidget?.(this.__swImageWidget);
                this.__swImageWidget = null;
            }

            // 清理旧文本展示区
            if (this.widgets) {
                const pos = this.widgets.findIndex((w) => w.name === "text");
                if (pos !== -1) {
                    for (let i = pos; i < this.widgets.length; i++) {
                        this.widgets[i].onRemove?.();
                    }
                    this.widgets.length = pos;
                }
            }

            // 图像输入：画布绘制预览。节点尺寸完全保持用户排版（不撑开不坍塌），
            // 图片在剩余可用区域按 contain 等比例适配居中显示
            if (images.length) {
                // addCustomWidget 内部会把节点尺寸强制设为 computeSize() 总和（最小布局高度），
                // 先记录用户当前高度，添加后恢复，保证执行后节点尺寸与用户排版一致
                const userH = this.size?.[1] ?? 0;
                const preview = new ImagePreviewWidget(this, images);
                this.__swImageWidget = preview;
                this.addCustomWidget(preview);
                // 恢复用户高度（addCustomWidget 会强制压缩到最小布局高度）
                if (userH > (this.size?.[1] ?? 0)) {
                    this.setSize?.([this.size[0], userH]);
                }
                this.setDirtyCanvas(true, true);
                return;
            }

            // 文本输入：渲染为只读多行输入框
            for (const list of texts) {
                const w = ComfyWidgets["STRING"](this, "text", ["STRING", { multiline: true }], app).widget;
                if (w.element) {
                    w.element.readOnly = true;
                    w.element.style.opacity = 0.6;
                }
                w.value = list;
            }

            // 清空原生图片预览状态：文本模式没有自定义预览 widget 占位，
            // 需阻止绘制循环（updatePreviews）把上次执行残留的图片预览 widget 重新加回来
            this.imgs = null;
            this.images = undefined;
        };

        // ── 节点缩放：图片预览随节点尺寸重绘（按钮为画布 widget，宽度自动适配） ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
