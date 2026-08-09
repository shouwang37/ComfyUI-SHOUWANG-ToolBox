import { app } from "../../../scripts/app.js";

const NODE_TYPE = "ShouWangResizeByEdge";

/**
 * 守望-图像按边缩放：模式切换联动显示/隐藏 widget。
 * 模式=分辨率 → 显示「分辨率」、隐藏「倍数」；模式=倍数 → 反之。
 * 隐藏仅影响显示（element + computeSize），widget 值仍随工作流序列化，切换模式不丢参数。
 */
app.registerExtension({
    name: "ShouWang.SideScaling",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;

            const setVisible = (widget, visible) => {
                if (!widget) return;
                if (widget.element) widget.element.style.display = visible ? "" : "none";
                // 布局隐藏：LiteGraph 计算高度时该 widget 贡献 0
                widget.computeSize = visible ? undefined : () => [0, -4];
            };
            const applyMode = () => {
                const modeWidget = node.widgets?.find((w) => w.name === "模式");
                if (!modeWidget) return;
                const isMulti = modeWidget.value === "倍数";
                setVisible(node.widgets?.find((w) => w.name === "分辨率"), !isMulti);
                setVisible(node.widgets?.find((w) => w.name === "倍数"), isMulti);
                // 按当前内容高度刷新节点尺寸（保留用户宽度）
                const size = node.computeSize();
                node.setSize([node.size?.[0] ?? size[0], size[1]]);
                node.setDirtyCanvas(true, true);
            };
            node.__swSideApply = applyMode;

            // 模式切换 → 联动显示/隐藏（保留原有 callback）
            const modeWidget = node.widgets?.find((w) => w.name === "模式");
            if (modeWidget && !modeWidget.__swSideBound) {
                modeWidget.__swSideBound = true;
                const origCallback = modeWidget.callback;
                modeWidget.callback = (value, canvas, n, pos, e) => {
                    origCallback?.(value, canvas, n, pos, e);
                    applyMode();
                };
            }
            applyMode();
        };

        // 加载工作流：configure 恢复保存的模式值后重新应用隐藏状态
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            this.__swSideApply?.();
        };
    },
});
