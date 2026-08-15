/**
 * ComfyUI-SHOUWANG-ToolBox — 守望-提示词输入前端扩展
 *
 * 为节点添加「复制 / 粘贴」两个画布按钮（位于输入框上方）：
 *   - 复制：把节点文本框内的当前字符串写入系统剪贴板
 *   - 粘贴：读取系统剪贴板文本，覆盖节点文本框内的全部内容
 *
 * 按钮为画布绘制 widget：规避新版 ComfyUI addDOMWidget 的 position:fixed 定位
 * 在画布缩放/平移时错位漂移的问题；宽度随节点宽度自适应（封顶 BTN_MAX_WIDTH，保底 BTN_MIN_WIDTH）。
 *
 * 剪贴板兼容性：优先 Clipboard API（本地 127.0.0.1 访问可用），
 * 非安全上下文（如局域网 IP 访问）下复制回退 execCommand，粘贴仅支持 API 方式。
 */

import { app } from "../../../scripts/app.js";

const NODE_TYPE = "ShouWangTextInput";
const DEFAULT_SIZE = [360, 220]; // 节点默认画布尺寸（宽 x 高，加载工作流时 configure 会恢复保存的尺寸）
const BTN_ROW_HEIGHT = 36; // 按钮行兜底高度（容器 padding + 按钮高度）
const BTN_HEIGHT = 28; // 按钮固定高度
const BTN_GAP = 6; // 按钮间距
const BTN_PAD = 4; // 按钮容器左右内边距
const BTN_MAX_WIDTH = 128; // 按钮最大宽度
const BTN_MIN_WIDTH = 48; // 按钮最小宽度（节点缩窄时的兜底）
const TITLE_HEIGHT = 30; // 节点标题栏高度（估算，用于计算 textarea 可用高度）
const BOTTOM_PAD = 10; // 节点底部留白（估算）
const TEXT_MIN_HEIGHT = 60; // textarea 最小高度

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
 * 读取系统剪贴板文本（需安全上下文，本地访问可用）
 * @returns {Promise<string|null>} 读取失败返回 null（空字符串是合法内容）
 */
async function readFromClipboard() {
    try {
        if (navigator.clipboard?.readText) {
            return await navigator.clipboard.readText();
        }
    } catch (e) {
        console.warn("[守望-提示词输入] 读取剪贴板失败:", e);
    }
    return null;
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
        this.serialize = false; // 按钮不参与序列化（内容经「text」widget 传递）
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

/**
 * 同步 textarea 高度跟随节点高度：节点拖大时输入框同步变大
 * 高度 = 节点高度 - 标题栏 - 按钮行 - 底部留白（最小 TEXT_MIN_HEIGHT）
 * 注意：不覆盖 widget.computeSize —— 其必须返回固定最小值，
 * 否则拖动缩放时 LiteGraph 按 computeSize 钻制目标尺寸（依赖当前高度会产生拖尾，向上缩不动）
 */
const syncTextAreaHeight = (node) => {
    const widget = node.widgets?.find((w) => w.name === "text");
    const el = widget?.element;
    if (!el) return;
    const nodeH = node.size?.[1];
    if (!nodeH) return;
    const h = Math.max(TEXT_MIN_HEIGHT, Math.floor(nodeH - TITLE_HEIGHT - BTN_ROW_HEIGHT - BOTTOM_PAD));
    el.style.height = `${h}px`;
};

app.registerExtension({
    name: "SHOUWANG.PromptInput",

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
        // 此后不再强制默认尺寸，与普通节点行为一致
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            if (info?.size) this.__configured = true;
        };

        // ── 节点创建：添加「复制 / 粘贴」画布按钮行（位于输入框之前） ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 同步先设一次默认尺寸（text widget 创建前的初始值）
            this.setSize([...DEFAULT_SIZE]);

            setTimeout(() => {
                // 已添加过则跳过（避免工作流重复加载时重复创建）
                if (this.widgets?.some((w) => w.name === "复制粘贴")) return;

                // 节点已从序列化恢复（加载工作流/ctrl+z 撤回）：不再强制默认尺寸，
                // 保持 configure 恢复的保存尺寸，避免覆盖导致布局跳变
                const restored = this.__configured;
                if (!restored) this.setSize([...DEFAULT_SIZE]);

                // 复制：把文本框当前内容写入系统剪贴板
                const copyBtn = { label: "复制", feedback: "已复制", onClick: async () => {
                    const widget = this.widgets?.find((w) => w.name === "text");
                    const text = widget?.value ?? "";
                    if (!text) throw new Error("内容为空");
                    await copyToClipboard(text);
                } };

                // 粘贴：读取系统剪贴板并覆盖文本框全部内容
                const pasteBtn = { label: "粘贴", feedback: "已粘贴", onClick: async () => {
                    const text = await readFromClipboard();
                    if (text === null) throw new Error("剪贴板不可用");
                    const widget = this.widgets?.find((w) => w.name === "text");
                    if (!widget) throw new Error("未找到文本框");
                    widget.value = text;
                    if (widget.element) widget.element.value = text; // 同步 textarea 显示
                    widget.callback?.(widget.value);
                    this.graph?.setDirtyCanvas(true, true);
                } };

                const btnRow = new CanvasButtonRowWidget(this, [copyBtn, pasteBtn]);
                // 按钮行插入到「text」输入框之前：输入框在上方先出现，按钮紧随其后
                const textIdx = this.widgets?.findIndex((w) => w.name === "text") ?? -1;
                if (textIdx > -1) this.widgets.splice(textIdx, 0, btnRow);
                else this.addCustomWidget(btnRow);

                // text widget 布局高度固定为最小高度：
                // 拖动缩放时 LiteGraph 按 computeSize 钻制目标尺寸，若其依赖当前高度会产生拖尾（向上缩不动）
                const textWidget = this.widgets?.find((w) => w.name === "text");
                if (textWidget && !textWidget.__swFixedCompute) {
                    textWidget.__swFixedCompute = true;
                    textWidget.computeSize = (width) => [width ?? this.size?.[0] ?? 200, TEXT_MIN_HEIGHT];
                }
                this.setDirtyCanvas(true, true);

                // 按节点初始尺寸同步 textarea 高度（与布局保持一致）
                syncTextAreaHeight(this);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        // ── 节点缩放：同步 textarea 高度与节点尺寸联动（按钮为画布 widget，宽度自动适配） ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            // 仅当尺寸实际变化时才解锁固定默认尺寸（用户拖动）；
            // 内部 setSize 传入相同尺寸或 configure 恢复时不误解锁
            const changed = !!this.__lastSize && !!size &&
                (size[0] !== this.__lastSize[0] || size[1] !== this.__lastSize[1]);
            this.__lastSize = size ? [size[0], size[1]] : null;
            if (changed) this.__userResized = true;
            syncTextAreaHeight(this);
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
