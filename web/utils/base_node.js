import { app } from "/scripts/app.js";
import { SERVICE as KEY_EVENT_SERVICE } from "./key_events_services.js";
import { LogLevel, rgthree } from "./rgthree.js";
import { addHelpMenuItem } from "./utils.js";
import { RgthreeHelpDialog } from "./dialog.js";
import { defineProperty, moveArrayItem } from "./shared_utils.js";
export class RgthreeBaseNode extends LGraphNode {
    constructor(title = RgthreeBaseNode.title, skipOnConstructedCall = true) {
        super(title);
        this.comfyClass = "__NEED_COMFY_CLASS__";
        this.nickname = "rgthree";
        this.isVirtualNode = false;
        this.removed = false;
        this.configuring = false;
        this._tempWidth = 0;
        this.__constructed__ = false;
        this.helpDialog = null;
        if (title == "__NEED_CLASS_TITLE__") {
            throw new Error("RgthreeBaseNode needs overrides.");
        }
        this.widgets = this.widgets || [];
        this.properties = this.properties || {};
        setTimeout(() => {
            if (this.comfyClass == "__NEED_COMFY_CLASS__") {
                throw new Error("RgthreeBaseNode needs a comfy class override.");
            }
            if (this.constructor.type == "__NEED_CLASS_TYPE__") {
                throw new Error("RgthreeBaseNode needs overrides.");
            }
            this.checkAndRunOnConstructed();
        });
        defineProperty(this, "mode", {
            get: () => {
                return this.rgthree_mode;
            },
            set: (mode) => {
                if (this.rgthree_mode != mode) {
                    const oldMode = this.rgthree_mode;
                    this.rgthree_mode = mode;
                    this.onModeChange(oldMode, mode);
                }
            },
        });
    }
    checkAndRunOnConstructed() {
        var _a;
        if (!this.__constructed__) {
            this.onConstructed();
            const [n, v] = rgthree.logger.logParts(LogLevel.DEV, `[RgthreeBaseNode] Child class did not call onConstructed for "${this.type}.`);
            (_a = console[n]) === null || _a === void 0 ? void 0 : _a.call(console, ...v);
        }
        return this.__constructed__;
    }
    onConstructed() {
        var _a;
        if (this.__constructed__)
            return false;
        this.type = (_a = this.type) !== null && _a !== void 0 ? _a : undefined;
        this.__constructed__ = true;
        rgthree.invokeExtensionsAsync("nodeCreated", this);
        return this.__constructed__;
    }
    configure(info) {
        this.configuring = true;
        super.configure(info);
        for (const w of this.widgets || []) {
            w.last_y = w.last_y || 0;
        }
        this.configuring = false;
    }
    clone() {
        const cloned = super.clone();
        if ((cloned === null || cloned === void 0 ? void 0 : cloned.properties) && !!window.structuredClone) {
            cloned.properties = structuredClone(cloned.properties);
        }
        cloned.graph = this.graph;
        return cloned;
    }
    onModeChange(from, to) {
    }
    async handleAction(action) {
        action;
    }
    removeWidget(widget) {
        var _a;
        if (typeof widget === "number") {
            widget = this.widgets[widget];
        }
        if (!widget)
            return;
        const canUseComfyUIRemoveWidget = false;
        if (canUseComfyUIRemoveWidget && typeof super.removeWidget === 'function') {
            super.removeWidget(widget);
        }
        else {
            const index = this.widgets.indexOf(widget);
            if (index > -1) {
                this.widgets.splice(index, 1);
            }
            (_a = widget.onRemove) === null || _a === void 0 ? void 0 : _a.call(widget);
        }
    }
    replaceWidget(widgetOrSlot, newWidget) {
        let index = null;
        if (widgetOrSlot) {
            index = typeof widgetOrSlot === "number" ? widgetOrSlot : this.widgets.indexOf(widgetOrSlot);
            this.removeWidget(this.widgets[index]);
        }
        index = index != null ? index : this.widgets.length - 1;
        if (this.widgets.includes(newWidget)) {
            moveArrayItem(this.widgets, newWidget, index);
        }
        else {
            this.widgets.splice(index, 0, newWidget);
        }
    }
    defaultGetSlotMenuOptions(slot) {
        var _a, _b;
        const menu_info = [];
        if ((_b = (_a = slot === null || slot === void 0 ? void 0 : slot.output) === null || _a === void 0 ? void 0 : _a.links) === null || _b === void 0 ? void 0 : _b.length) {
            menu_info.push({ content: "Disconnect Links", slot });
        }
        let inputOrOutput = slot.input || slot.output;
        if (inputOrOutput) {
            if (inputOrOutput.removable) {
                menu_info.push(inputOrOutput.locked ? { content: "Cannot remove" } : { content: "Remove Slot", slot });
            }
            if (!inputOrOutput.nameLocked) {
                menu_info.push({ content: "Rename Slot", slot });
            }
        }
        return menu_info;
    }
    onRemoved() {
        var _a;
        (_a = super.onRemoved) === null || _a === void 0 ? void 0 : _a.call(this);
        this.removed = true;
    }
    static setUp(...args) {
    }
    getHelp() {
        return "";
    }
    showHelp() {
        const help = this.getHelp() || this.constructor.help;
        if (help) {
            this.helpDialog = new RgthreeHelpDialog(this, help).show();
            this.helpDialog.addEventListener("close", (e) => {
                this.helpDialog = null;
            });
        }
    }
    onKeyDown(event) {
        KEY_EVENT_SERVICE.handleKeyDownOrUp(event);
        if (event.key == "?" && !this.helpDialog) {
            this.showHelp();
        }
    }
    onKeyUp(event) {
        KEY_EVENT_SERVICE.handleKeyDownOrUp(event);
    }
    getExtraMenuOptions(canvas, options) {
        var _a, _b, _c, _d, _e, _f;
        if (super.getExtraMenuOptions) {
            (_a = super.getExtraMenuOptions) === null || _a === void 0 ? void 0 : _a.apply(this, [canvas, options]);
        }
        else if ((_c = (_b = this.constructor.nodeType) === null || _b === void 0 ? void 0 : _b.prototype) === null || _c === void 0 ? void 0 : _c.getExtraMenuOptions) {
            (_f = (_e = (_d = this.constructor.nodeType) === null || _d === void 0 ? void 0 : _d.prototype) === null || _e === void 0 ? void 0 : _e.getExtraMenuOptions) === null || _f === void 0 ? void 0 : _f.apply(this, [canvas, options]);
        }
        const help = this.getHelp() || this.constructor.help;
        if (help) {
            addHelpMenuItem(this, help, options);
        }
        return [];
    }
}
RgthreeBaseNode.exposedActions = [];
RgthreeBaseNode.title = "__NEED_CLASS_TITLE__";
RgthreeBaseNode.type = "__NEED_CLASS_TYPE__";
RgthreeBaseNode.category = "rgthree";
RgthreeBaseNode._category = "rgthree";
export class RgthreeBaseVirtualNode extends RgthreeBaseNode {
    constructor(title = RgthreeBaseNode.title) {
        super(title, false);
        this.isVirtualNode = true;
    }
    static setUp() {
        if (!this.type) {
            throw new Error(`Missing type for RgthreeBaseVirtualNode: ${this.title}`);
        }
        LiteGraph.registerNodeType(this.type, this);
        if (this._category) {
            this.category = this._category;
        }
    }
}
