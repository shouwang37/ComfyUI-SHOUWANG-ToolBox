/**
 * ComfyUI-SHOUWANG-ToolBox — AnythingSelect 动态输入端口前端扩展
 *
 * 输入端口数量由「输入数量」参数控制（1~99）：
 *   - 修改参数 → 端口数量即时增减（已连接的端口不会被删除）
 *   - 输出端口固定 1 个，按「切换模式」输出：顺序取第一个非空输入，或按「选择序号」取指定输入
 *   - 切换模式为「选择」时自动显示「选择序号」输入框（默认 1），「顺序」时隐藏
 *
 * 类型锁定（递归追溯，借鉴 rgthree-comfy 的 followConnectionUntilType 思路）：
 * 从第一个已连接输入出发，沿连接链逐级向上追溯真实类型（穿透通配符 "*" 节点，
 * 支持任意切换器串联），将锁定类型统一应用到所有输入端口与输出端口；
 * 全部断开后自动解锁，恢复通配符 "*"。
 */

import { app } from "../../../scripts/app.js";

const MAX_INPUTS = 99; // 与 src/utils/anything_select.py 中 AnythingSelect.MAX_INPUTS 保持一致
const DEFAULT_COUNT = 5; // 默认输入端口数量
const MAX_TRACE_DEPTH = 10; // 递归追溯最大深度，防止异常链路死循环

/**
 * 递归追溯真实类型：从节点的输入连接出发，逐级向上寻找第一个真实类型。
 * 若源端口是通配符 "*"（如串联的另一个切换器），则进入该节点继续追溯。
 * @returns {string|null} 真实类型；找不到时返回 null
 */
const traceInputType = (node, depth = 0) => {
    if (depth > MAX_TRACE_DEPTH || !node) return null;

    for (const input of node.inputs || []) {
        if (input.link == null) continue;

        const link = node.graph?.links?.[input.link];
        if (!link) continue;

        // 沿连接链找到源头节点与源端口
        const originNode = node.graph?.getNodeById(link.origin_id);
        const originSlot = originNode?.outputs?.[link.origin_slot];

        // 源端口是真实类型 → 采用
        if (originSlot?.type && originSlot.type !== "*") {
            return originSlot.type;
        }
        // 源端口也是通配符 → 进入源头节点递归追溯
        if (originSlot?.type === "*") {
            const deeperType = traceInputType(originNode, depth + 1);
            if (deeperType) return deeperType;
        }
    }
    return null;
};

/**
 * 类型锁定：以递归追溯到的真实类型，统一所有输入端口与输出端口类型
 * @returns {string|null} 锁定类型；无连接时为 null（端口恢复通配符 "*"）
 */
const refreshLock = (node) => {
    const inputs = node.inputs || [];
    const lockedType = traceInputType(node);

    // 统一输入端口类型（锁定为真实类型，未锁定时为通配符）
    for (const input of inputs) {
        input.type = lockedType || "*";
    }

    // 统一输出端口类型
    const output = node.outputs?.[0];
    if (output) {
        output.type = lockedType || "*";
    }

    return lockedType;
};

/**
 * 按「输入数量」参数同步端口数量
 * 数量不足 → 追加端口；数量超出 → 从末尾移除未连接的端口（已连接的端口不受影响）
 */
const syncInputCount = (node) => {
    const countWidget = node.widgets?.find(w => w.name === "输入数量");
    const target = Math.max(1, Math.min(MAX_INPUTS, countWidget?.value ?? DEFAULT_COUNT));
    const inputs = node.inputs || [];

    // 同步「选择序号」上限为当前输入数量，超出时自动回落
    const seqWidget = node.widgets?.find(w => w.name === "选择序号");
    if (seqWidget) {
        seqWidget.options.max = target;
        if (seqWidget.value > target) seqWidget.value = target;
    }

    // 数量不足 → 追加端口（命名「输入N」，与后端 INPUT_TYPES 键保持一致）
    while (inputs.length < target) {
        node.addInput(`输入${inputs.length + 1}`, "*");
    }
    // 数量超出 → 从末尾移除未连接的端口
    for (let i = inputs.length - 1; i >= target; i--) {
        if (inputs[i].link == null) {
            node.removeInput(i);
        }
    }

    // 恢复类型锁定并刷新
    refreshLock(node);
    node.setSize?.(node.computeSize());
    node.graph?.setDirtyCanvas(true, true);
};

/**
 * 按「切换模式」参数显示/隐藏「选择序号」输入框：
 * 顺序 → 隐藏；选择 → 显示（默认 1）
 */
const syncModeWidget = (node) => {
    const modeWidget = node.widgets?.find(w => w.name === "切换模式");
    const seqWidget = node.widgets?.find(w => w.name === "选择序号");
    if (!seqWidget) return;

    seqWidget.type = modeWidget?.value === "选择" ? "number" : "hidden";
    node.setSize?.(node.computeSize());
    node.graph?.setDirtyCanvas(true, true);
};

app.registerExtension({
    name: "SHOUWANG.AnythingSelect",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 仅处理目标节点
        if (nodeData.name !== "ShouWangAnythingSelect") return;

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
                const modeWidget = this.widgets?.find(w => w.name === "切换模式");
                if (modeWidget && !modeWidget.__modeBound) {
                    modeWidget.__modeBound = true;
                    modeWidget.callback = () => syncModeWidget(this);
                }
                // 手动输入「选择序号」超出当前输入数量时自动钳制到上限
                const seqWidget = this.widgets?.find(w => w.name === "选择序号");
                if (seqWidget && !seqWidget.__seqBound) {
                    seqWidget.__seqBound = true;
                    seqWidget.callback = () => {
                        const countWidget = this.widgets?.find(w => w.name === "输入数量");
                        const max = Math.max(1, Math.min(MAX_INPUTS, countWidget?.value ?? DEFAULT_COUNT));
                        if (seqWidget.value > max) {
                            seqWidget.value = max;
                            this.graph?.setDirtyCanvas(true, true);
                        }
                    };
                }
                syncInputCount(this);
                syncModeWidget(this);
            }, 0);
        };

        // ── 连接变化：仅刷新类型锁定（端口数量由「输入数量」参数控制）──
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (slot_type, slot_index, is_connected, link_info) {
            const result = onConnectionsChange?.apply(this, arguments);

            // 仅处理输入端口（LiteGraph.INPUT = 1）
            if (slot_type !== 1) return result;

            // 类型锁定：以递归追溯到的真实类型统一所有端口
            refreshLock(this);

            // 重算节点尺寸并刷新画布
            this.setSize?.(this.computeSize());
            this.graph?.setDirtyCanvas(true, true);
            return result;
        };
    },
});
