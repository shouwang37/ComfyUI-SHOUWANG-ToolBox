import { app } from "/scripts/app.js";
import { SERVICE as KEY_EVENT_SERVICE } from "./key_events_services.js";
import { SERVICE as BOOKMARKS_SERVICE } from "./bookmarks_services.js";
import { getClosestOrSelf, query } from "./utils_dom.js";
import { wait } from "./shared_utils.js";
import { findFromNodeForSubgraph } from "./utils.js";

const NODE_TYPE = "ShouWangBookmark";

/**
 * 守望-书签节点（参考 rgthree-comfy 的 Bookmark）。
 * 可放置在工作流任意位置并设定快捷键；按下快捷键即跳转到书签节点（位于画布左上角）并应用设定的缩放。
 * 虚拟节点：无输入输出端口，不参与执行。
 *
 * 注意：本节点同时存在后端类（保证菜单中文名/工具分类），前端不能再用 registerCustomNodes
 * 注册同名自定义类（会被后端 NodeDefs 覆盖导致参数丢失），必须通过 beforeRegisterNodeDef
 * 在默认类原型上覆写行为并注入 widget。
 */
app.registerExtension({
    name: "ShouWang.Bookmark",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：注入快捷键/缩放 widget、标记虚拟节点、标题显示 🔖 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            if (this.__swBookmarkInit) return;
            this.__swBookmarkInit = true;

            this.serialize_widgets = true; // widget 值随工作流保存/恢复
            this.isVirtualNode = true;     // 不参与执行排队（后端 noop 亦无副作用）

            // 快捷键 widget（自动分配下一个未占用的默认键）
            const nextShortcutChar = BOOKMARKS_SERVICE.getNextShortcut();
            this.addWidget(
                "text",
                "快捷键",
                nextShortcutChar,
                (value, ...args) => {
                    value = value.trim()[0] || "1";
                },
                {
                    y: 8,
                },
            );
            // 跳转缩放 widget
            this.addWidget("number", "缩放", 1, (value) => {}, {
                y: 8 + LiteGraph.NODE_WIDGET_HEIGHT + 4,
                max: 2,
                min: 0.5,
                precision: 2,
            });

            this.keypressBound = this.onBookmarkKeypress.bind(this);
            this.title = "🔖";
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
        };

        // ── 加入/移除画布：注册/注销快捷键监听 ──
        const onAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function (graph) {
            onAdded?.apply(this, arguments);
            KEY_EVENT_SERVICE.addEventListener("keydown", this.keypressBound);
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            onRemoved?.apply(this, arguments);
            KEY_EVENT_SERVICE.removeEventListener("keydown", this.keypressBound);
        };

        // ── 按键跳转：仅按下快捷键本身（可选附带 shift）即触发 ──
        nodeType.prototype.onBookmarkKeypress = function (event) {
            const originalEvent = event.detail.originalEvent;
            const target = originalEvent.target;
            if (getClosestOrSelf(target, 'input,textarea,[contenteditable="true"]')) {
                return;
            }
            if (KEY_EVENT_SERVICE.areOnlyKeysDown(this.widgets[0].value, true)) {
                this.canvasToBookmark();
                originalEvent.preventDefault();
                originalEvent.stopPropagation();
            }
        };

        // ── shortcut_key 输入框：补录按键组合（LiteGraph 会先弹出 graphdialog 输入框）──
        const onMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function (event, pos, graphCanvas) {
            const ret = onMouseDown?.apply(this, arguments);
            const input = query(".graphdialog > input.value");
            if (input && input.value === this.widgets[0]?.value) {
                input.addEventListener("keydown", (e) => {
                    KEY_EVENT_SERVICE.handleKeyDownOrUp(e);
                    e.preventDefault();
                    e.stopPropagation();
                    input.value = Object.keys(KEY_EVENT_SERVICE.downKeys).join(" + ");
                });
            }
            return ret;
        };

        // ── 跳转：画布定位到书签位置（节点左上角偏移 16,40）并应用缩放 ──
        nodeType.prototype.canvasToBookmark = async function () {
            const canvas = app.canvas;
            if (this.graph !== app.canvas.getCurrentGraph()) {
                const subgraph = this.graph;
                const fromNode = findFromNodeForSubgraph(subgraph.id);
                canvas.openSubgraph(subgraph, fromNode);
                await wait(16);
            }
            if (canvas?.ds?.offset) {
                canvas.ds.offset[0] = -this.pos[0] + 16;
                canvas.ds.offset[1] = -this.pos[1] + 40;
            }
            if (canvas?.ds?.scale != null) {
                canvas.ds.scale = Number(this.widgets[1]?.value || 1);
            }
            canvas.setDirty(true, true);
        };

        // 无输入输出端口，抵消 LiteGraph 假定至少有一个插槽的高度
        nodeType.slot_start_y = -20;
    },
});
