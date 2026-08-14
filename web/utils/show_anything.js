/**
 * ComfyUI-SHOUWANG-ToolBox — 展示任何节点前端扩展
 *
 * 执行后把后端返回的文本列表渲染为只读多行输入框（参考 Easy-Use showAnything）：
 *   - 清空上一次的「text」展示区后逐条重建
 *   - 只读样式（半透明），不可编辑
 *   - 输入参数区提供「复制」按钮：点击后复制节点当前展示的全部文本内容
 */

import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

const NODE_TYPE = "ShouWangShowAnything";
const BTN_ROW_HEIGHT = 36; // 按钮行兜底高度（容器 padding + 按钮高度）
const BTN_HEIGHT = 28; // 按钮固定高度
const BTN_PAD = 4; // 按钮容器左右内边距
const BTN_MAX_WIDTH = 128; // 按钮最大宽度
const BTN_MIN_WIDTH = 48; // 按钮最小宽度（节点缩窄时的兜底）

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
 * 按节点宽度同步按钮宽度：按钮总宽不超出节点内容宽度
 * 节点越宽按钮越宽（封顶 BTN_MAX_WIDTH），节点缩窄时按钮同步收窄（保底 BTN_MIN_WIDTH）
 */
const syncButtonWidth = (node, copyBtn) => {
    const nodeWidth = node.size?.[0] ?? 200;
    const avail = Math.max(BTN_MIN_WIDTH + BTN_PAD * 2, nodeWidth - BTN_PAD * 2);
    const btnWidth = Math.min(BTN_MAX_WIDTH, avail);
    copyBtn.style.width = `${btnWidth}px`;
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
    name: "SHOUWANG.ShowAnything",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：添加「复制」按钮（不强制固定尺寸，执行后按内容自动撑开） ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            setTimeout(() => {
                // 已添加过则跳过（避免工作流重复加载时重复创建）
                if (this.widgets?.some((w) => w.name === "复制粘贴")) return;

                const el = document.createElement("div");
                el.style.cssText = `display:flex;justify-content:center;gap:0;padding:${BTN_PAD}px;`;

                // 复制：把节点当前展示的全部文本内容写入系统剪贴板
                const copyBtn = createButton("复制", "已复制", async () => {
                    const texts = this.widgets
                        ?.filter((w) => w.name === "text")
                        .map((w) => w.value ?? "")
                        .filter((t) => t !== "");
                    if (!texts?.length) throw new Error("内容为空");
                    await copyToClipboard(texts.join("\n"));
                });

                el.appendChild(copyBtn);

                // 保存按钮引用：节点缩放时按节点宽度同步按钮宽度
                this.__copyPasteBtns = { copyBtn };

                this.addDOMWidget("复制粘贴", "custom", el, {
                    getHeight: () => el.offsetHeight || BTN_ROW_HEIGHT,
                    serialize: false, // 按钮组不参与序列化（展示内容经「text」widget 传递）
                });
                syncButtonWidth(this, copyBtn);
                this.setDirtyCanvas(true, true);
            }, 0);
        };

        const onExecuted = nodeType.prototype.onExecuted;

        // 执行后：将返回的文本列表渲染为只读多行输入框
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);

            const texts = message?.text ?? [];
            if (this.widgets) {
                const pos = this.widgets.findIndex((w) => w.name === "text");
                if (pos !== -1) {
                    for (let i = pos; i < this.widgets.length; i++) {
                        this.widgets[i].onRemove?.();
                    }
                    this.widgets.length = pos;
                }
            }
            for (const list of texts) {
                const w = ComfyWidgets["STRING"](this, "text", ["STRING", { multiline: true }], app).widget;
                if (w.element) {
                    w.element.readOnly = true;
                    w.element.style.opacity = 0.6;
                }
                w.value = list;
            }
        };

        // ── 节点缩放：同步按钮宽度，与节点宽度联动 ──
        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            onResize?.apply(this, arguments);
            const btns = this.__copyPasteBtns;
            if (btns) syncButtonWidth(this, btns.copyBtn);
            this.graph?.setDirtyCanvas(true, true);
        };
    },
});
