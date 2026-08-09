/**
 * ComfyUI-SHOUWANG-ToolBox — PromptMerger 动态输入端口前端扩展
 *
 * 输入端口数量由「输入数量」参数控制（1~99）：
 *   - 默认 1 个输入端口，修改参数 → 端口数量即时增减（已连接的端口不会被删除）
 *   - 输出端口固定 1 个，按「连接符号」拼接所有非空输入
 *   - 输入端口类型固定为 STRING
 */

import { app } from "../../../scripts/app.js";

const MAX_INPUTS = 99; // 与 src/string/prompt_merger.py 中 PromptMerger.MAX_INPUTS 保持一致
const DEFAULT_COUNT = 1; // 默认输入端口数量

/**
 * 按「输入数量」参数同步端口数量
 * 数量不足 → 追加端口；数量超出 → 从末尾移除未连接的端口（已连接的端口不受影响）
 */
const syncInputCount = (node) => {
    const countWidget = node.widgets?.find(w => w.name === "输入数量");
    const target = Math.max(1, Math.min(MAX_INPUTS, countWidget?.value ?? DEFAULT_COUNT));
    const inputs = node.inputs || [];

    // 数量不足 → 追加端口（命名「提示词N」，与后端 INPUT_TYPES 键保持一致）
    while (inputs.length < target) {
        node.addInput(`提示词${inputs.length + 1}`, "STRING");
    }
    // 数量超出 → 从末尾移除未连接的端口
    for (let i = inputs.length - 1; i >= target; i--) {
        if (inputs[i].link == null) {
            node.removeInput(i);
        }
    }

    // 重算节点尺寸并刷新画布
    node.setSize?.(node.computeSize());
    node.graph?.setDirtyCanvas(true, true);
};

app.registerExtension({
    name: "SHOUWANG.PromptMerger",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 仅处理目标节点
        if (nodeData.name !== "ShouWangPromptMerger") return;

        // ── 节点创建：绑定「输入数量」参数回调，并按参数同步端口数量 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 延迟到链接恢复后执行，避免误删已连接的端口
            setTimeout(() => {
                const countWidget = this.widgets?.find(w => w.name === "输入数量");
                if (countWidget && !countWidget.__syncBound) {
                    countWidget.__syncBound = true;
                    countWidget.callback = () => syncInputCount(this);
                }
                syncInputCount(this);
            }, 0);
        };
    },
});
