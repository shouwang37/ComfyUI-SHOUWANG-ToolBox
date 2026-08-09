/**
 * ComfyUI-SHOUWANG-ToolBox — 图像拼接对比节点前端扩展
 *
 * 「组数」参数与输入端口关联（数字为几就显示几组）：
 *   - 端口按「图像N、标题N」交替排列（图像必须输入，标题端口可为空）
 *   - 组数增减时追加/移除未连接的端口（已连接的端口不会被删除）
 *   - 「间距颜色」转换为取色器（type="color"，不支持时退化为文本输入）
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_TYPE = "ShouWangImageSpliceComparison";
const MAX_GROUPS = 9; // 与 src/image/img_splice_comparison.py 中 MAX_GROUPS 保持一致
const DEFAULT_GROUPS = 2;
const DEFAULT_WIDTH = 520; // 节点默认宽度（新建节点初始放宽，避免默认过窄）

/** 按「组数」参数同步端口：组数为 N 时显示 图像1、标题1、图像2、标题2 ... 图像N、标题N */
const syncGroups = (node) => {
    const countWidget = node.widgets?.find(w => w.name === "组数");
    const target = Math.max(1, Math.min(MAX_GROUPS, countWidget?.value ?? DEFAULT_GROUPS));
    const inputs = node.inputs || [];

    // 1. 移除超出 target*2 的未连接端口（已连接的保留，不会被删除）
    for (let i = inputs.length - 1; i >= target * 2; i--) {
        if (inputs[i].link == null) {
            node.removeInput(i);
        }
    }

    // 2. 校验位置：名字与「图像N/标题N」位置不匹配的未连接端口移除重建
    //    （兼容旧版本节点加载后端口只有图像、没有标题的情况）
    for (let i = inputs.length - 1; i >= 0; i--) {
        const input = inputs[i];
        if (input.link != null) continue;
        const expectName = i % 2 === 0 ? `图像${i / 2 + 1}` : `标题${(i - 1) / 2 + 1}`;
        if (input.name !== expectName) {
            node.removeInput(i);
        }
    }

    // 3. 按 图像N、标题N 交替补齐到 target*2 个端口
    while (inputs.length < target * 2) {
        const idx = inputs.length;
        if (idx % 2 === 0) {
            node.addInput(`图像${idx / 2 + 1}`, "IMAGE");
        } else {
            node.addInput(`标题${(idx - 1) / 2 + 1}`, "STRING");
        }
    }

    // 高度随内容更新，宽度保留当前值（初始宽度见 onNodeCreated，用户拖拽的宽度不被重置）
    const size = node.computeSize();
    node.setSize?.([node.size?.[0] ?? size[0], size[1]]);
    node.graph?.setDirtyCanvas(true, true);
};

app.registerExtension({
    name: "SHOUWANG.ImageSpliceComparison",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：绑定「组数」回调，初始化端口/取色器，刷新字体下拉 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            // 延迟到链接恢复后执行，避免误删已连接的端口
            setTimeout(() => {
                const countWidget = this.widgets?.find(w => w.name === "组数");
                if (countWidget && !countWidget.__syncBound) {
                    countWidget.__syncBound = true;
                    countWidget.callback = () => syncGroups(this);
                }
                // 「间距颜色」「标题颜色」转为取色器（前端不支持 color 类型时保持文本输入，仍可填 #RRGGBB）
                for (const name of ["间距颜色", "标题颜色"]) {
                    const colorWidget = this.widgets?.find(w => w.name === name);
                    if (colorWidget && colorWidget.type !== "color") {
                        colorWidget.__origType = colorWidget.type;
                        colorWidget.type = "color";
                    }
                }
                // 清理旧版本残留的「标题N」输入框（标题已改为端口，不再使用 widget）
                for (let i = 1; i <= MAX_GROUPS; i++) {
                    const titleWidget = this.widgets?.find(w => w.name === `标题${i}`);
                    if (titleWidget && this.removeWidget) {
                        this.removeWidget(titleWidget);
                    }
                }
                this._swRefreshFontFiles();
                // 初始宽度：新建节点默认偏窄（约 200px），放宽到 DEFAULT_WIDTH；已保存宽度的节点不强制
                if ((this.size?.[0] ?? 0) < DEFAULT_WIDTH - 40) {
                    this.setSize([DEFAULT_WIDTH, this.computeSize()[1]]);
                }
                syncGroups(this);
            }, 0);
        };

        // 刷新「标题字体」下拉列表（保留当前选择，不存在则切到第一个）
        nodeType.prototype._swRefreshFontFiles = async function () {
            try {
                const resp = await api.fetchApi("/shouwang/font_files");
                const data = await resp.json();
                const widget = this.widgets?.find(w => w.name === "标题字体");
                if (!widget) return;
                const files = Array.isArray(data?.files) ? data.files : [];
                widget.options = { values: files.length ? files : ["(无字体文件)"] };
                if (!files.includes(widget.value)) {
                    widget.value = files[0] ?? "(无字体文件)";
                }
            } catch (e) {
                // 后端不可用或尚未就绪时跳过刷新
            }
        };
    },
});
