/**
 * ComfyUI-SHOUWANG-ToolBox — Tagger 反推器二级参数动态显隐前端扩展
 *
 * 模型切换时按模型类型显示/隐藏二级参数：
 *   - JTP 类模型（safetensors 引擎，如 JTP_PILOT2）无标签类别 → 隐藏「角色阈值/角色开关/常规开关/版权开关」
 *   - 其他模型（WD14 / pixai 等）→ 全部参数显示
 *
 * 说明：
 *   - 后端 INPUT_TYPES 静态声明全部参数（避免 ComfyUI get_object_info 序列化 method 崩溃）
 *   - 前端负责按模型类型显隐参数，规则与 src/string/prompt_tagger.py 的 _tagger_kind 保持一致：
 *     JTP 判断 = 模型文件夹名包含 "jtp"（不区分大小写）
 */

import { app } from "../../../scripts/app.js";

// JTP 模型需隐藏的类别二级参数（与后端 generate 的类别参数对应）
const JTP_PARAM_HIDDEN = ["角色阈值", "角色开关", "常规开关", "版权开关"];

const DEFAULT_WIDTH = 420; // 节点默认宽度（新建节点初始放宽，避免默认过窄）

// 15 位随机种子（100000000000000 ~ 999999999999999）
const newRandomSeed = () => Math.floor(Math.random() * (10 ** 15 - 10 ** 14)) + 10 ** 14;

/**
 * 按当前「模型名称」应用参数显隐
 */
const applyParamsVisibility = (node) => {
    const modelWidget = node.widgets?.find(w => w.name === "模型名称");
    const modelName = String(modelWidget?.value ?? "");
    const isJtp = /jtp/i.test(modelName);

    for (const widget of node.widgets || []) {
        if (JTP_PARAM_HIDDEN.includes(widget.name)) {
            widget.hidden = isJtp;
        }
    }

    // 高度随内容更新，宽度保留当前值（初始宽度见 onNodeCreated，用户拖拽的宽度不被重置）
    const size = node.computeSize();
    node.setSize?.([node.size?.[0] ?? size[0], size[1]]);
    node.graph?.setDirtyCanvas(true, true);
};

/**
 * 随机模式：点击「运行」时为节点生成新的 15 位随机种子（固定模式/切换模式不改动种子）
 * @returns {boolean} 是否已更新种子
 */
const randomizeSeed = (node) => {
    const modeWidget = node.widgets?.find(w => w.name === "种子模式");
    if (String(modeWidget?.value) !== "随机") return false;

    const seedWidget = node.widgets?.find(w => w.name === "种子");
    if (!seedWidget) return false;

    seedWidget.value = newRandomSeed();
    // 同步输入框显示文本（widget.value 用于提交，inputEl 用于展示）
    if (seedWidget.inputEl) seedWidget.inputEl.value = String(seedWidget.value);
    node.graph?.setDirtyCanvas(true, true);
    return true;
};

app.registerExtension({
    name: "SHOUWANG.PromptTagger",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        // 仅处理反推器节点
        if (nodeData.name !== "ShouWangVizTagger") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 延迟到 widget 构建完成、链接恢复后执行
            setTimeout(() => {
                // 切换模型 → 即时刷新二级参数显隐
                // 注意：不绑定「种子模式」callback —— 切换模式不应改变种子，
                // 仅随机状态下点击「运行」时才生成新种子（见下方 setup 的 queuePrompt 钩子）
                const modelWidget = this.widgets?.find(w => w.name === "模型名称");
                if (modelWidget && !modelWidget.__taggerBound) {
                    modelWidget.__taggerBound = true;
                    modelWidget.callback = () => applyParamsVisibility(this);
                }

                applyParamsVisibility(this);
                // 初始宽度：新建节点默认偏窄，放宽到 DEFAULT_WIDTH；
                // 已保存宽度或已从序列化恢复（加载工作流/ctrl+z 撤回）的节点不强制
                if (!this.__configured && (this.size?.[0] ?? 0) < DEFAULT_WIDTH - 40) {
                    this.setSize([DEFAULT_WIDTH, this.computeSize()[1]]);
                }
            }, 0);
        };

        // configure 恢复（加载工作流 / ctrl+z 撤回）：标记已从序列化恢复尺寸，
        // 此后不再强制初始宽度，保持恢复的保存尺寸，避免撤回后布局跳变
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            if (info?.size) this.__configured = true;
        };
    },

    async setup() {
        // 点击「运行」：随机模式的节点每次生成新的 15 位随机种子（本次执行即使用新种子）
        const origQueuePrompt = app.queuePrompt.bind(app);
        app.queuePrompt = async function (...args) {
            for (const node of app.graph?._nodes ?? []) {
                if (node.type === "ShouWangVizTagger") {
                    randomizeSeed(node);
                }
            }
            return origQueuePrompt(...args);
        };
    },
});
