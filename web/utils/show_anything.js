/**
 * ComfyUI-SHOUWANG-ToolBox — 展示任何节点前端扩展
 *
 * 执行后把后端返回的文本列表渲染为只读多行输入框（参考 Easy-Use showAnything）：
 *   - 清空上一次的「text」展示区后逐条重建
 *   - 只读样式（半透明），不可编辑
 */

import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

const NODE_TYPE = "ShouWangShowAnything";
const DEFAULT_SIZE = [100, 60]; // 节点默认画布尺寸（系统默认约 140x60，按用户要求缩小；严格 0.5 倍会小于最小可用尺寸，故取最小可用值）

app.registerExtension({
    name: "SHOUWANG.ShowAnything",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // 初始尺寸：覆盖系统默认计算值（加载工作流时 configure 会恢复保存的尺寸，不受影响）
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            this.setSize([...DEFAULT_SIZE]);
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
    },
});
