/**
 * ComfyUI-SHOUWANG-ToolBox — 守望-提示词输入前端扩展
 *
 * 为节点添加「复制 / 粘贴」两个按钮：
 *   - 复制：把节点文本框内的当前字符串写入系统剪贴板
 *   - 粘贴：读取系统剪贴板文本，覆盖节点文本框内的全部内容
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
 * 同步 textarea 高度跟随节点高度：节点拖大时输入框同步变大
 * 高度 = 节点高度 - 标题栏 - 按钮行 - 底部留白；同时覆盖 widget.computeSize，
 * 让后续 widget（按钮行）按新高度参与布局，避免被遮挡或错位
 */
const syncTextAreaHeight = (node) => {
    const widget = node.widgets?.find((w) => w.name === "text");
    const el = widget?.element;
    if (!el) return;
    const nodeH = node.size?.[1];
    if (!nodeH) return;
    const h = Math.max(TEXT_MIN_HEIGHT, Math.floor(nodeH - TITLE_HEIGHT - BTN_ROW_HEIGHT - BOTTOM_PAD));
    el.style.height = `${h}px`;
    widget.computeSize = (width) => [width ?? el.offsetWidth, h];
};

/**
 * 创建带点击反馈的按钮：点击后短暂显示反馈文案，1.2s 后恢复
 */
function createButton(label, feedbackLabel, onClick) {
    const btn = document.createElement("button");
    btn.textContent = label;
    // 宽度不在此固定：由 syncButtonWidth 按节点宽度动态计算，避免按钮组脱离节点
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

        // ── 节点创建：添加「复制 / 粘贴」按钮组 ──
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

                const el = document.createElement("div");
                el.style.cssText = `display:flex;justify-content:center;gap:${BTN_GAP}px;padding:${BTN_PAD}px;`;

                // 复制：把文本框当前内容写入系统剪贴板
                const copyBtn = createButton("复制", "已复制", async () => {
                    const widget = this.widgets?.find((w) => w.name === "text");
                    const text = widget?.value ?? "";
                    if (!text) throw new Error("内容为空");
                    await copyToClipboard(text);
                });

                // 粘贴：读取系统剪贴板并覆盖文本框全部内容
                const pasteBtn = createButton("粘贴", "已粘贴", async () => {
                    const text = await readFromClipboard();
                    if (text === null) throw new Error("剪贴板不可用");
                    const widget = this.widgets?.find((w) => w.name === "text");
                    if (!widget) throw new Error("未找到文本框");
                    widget.value = text;
                    if (widget.element) widget.element.value = text; // 同步 textarea 显示
                    widget.callback?.(widget.value);
                    this.graph?.setDirtyCanvas(true, true);
                });

                el.appendChild(copyBtn);
                el.appendChild(pasteBtn);

                // 保存按钮引用：节点缩放时按节点宽度同步按钮宽度
                this.__copyPasteBtns = { copyBtn, pasteBtn };

                this.addDOMWidget("复制粘贴", "custom", el, {
                    getHeight: () => el.offsetHeight || BTN_ROW_HEIGHT,
                    serialize: false, // 按钮组不参与序列化（内容经「text」widget 传递）
                });
                // 按钮组加入后再设一次默认尺寸（widget 集合变化后）；已恢复的节点跳过
                if (!restored) this.setSize([...DEFAULT_SIZE]);
                // 按节点初始尺寸初始化：按钮宽度 + textarea 高度（与布局保持一致）
                syncButtonWidth(this, copyBtn, pasteBtn);
                syncTextAreaHeight(this);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        // ── 节点缩放：同步按钮宽度与 textarea 高度，与节点尺寸联动 ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            // 仅当尺寸实际变化时才解锁固定默认尺寸（用户拖动）；
            // 内部 setSize 传入相同尺寸或 configure 恢复时不误解锁
            const changed = !!this.__lastSize && !!size &&
                (size[0] !== this.__lastSize[0] || size[1] !== this.__lastSize[1]);
            this.__lastSize = size ? [size[0], size[1]] : null;
            if (changed) this.__userResized = true;
            const btns = this.__copyPasteBtns;
            if (btns) syncButtonWidth(this, btns.copyBtn, btns.pasteBtn);
            syncTextAreaHeight(this);
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
