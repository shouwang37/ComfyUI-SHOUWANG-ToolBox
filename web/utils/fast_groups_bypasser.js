import { app } from "/scripts/app.js";
import { NodeTypesString } from "./constants.js";
import { BaseFastGroupsModeChanger } from "./fast_groups_muter.js";
export class ShouWangIgnoreMultiGroups extends BaseFastGroupsModeChanger {
    constructor(title = ShouWangIgnoreMultiGroups.title) {
        super(title);
        this.comfyClass = NodeTypesString.FAST_GROUPS_BYPASSER;
        this.helpActions = "bypass and enable";
        this.modeOn = LiteGraph.ALWAYS;
        this.modeOff = 4;
        this.onConstructed();
    }
}
ShouWangIgnoreMultiGroups.type = NodeTypesString.FAST_GROUPS_BYPASSER;
ShouWangIgnoreMultiGroups.title = "守望-忽略多组🐢";
ShouWangIgnoreMultiGroups.exposedActions = ["全部忽略", "全部启用", "全部切换"];
ShouWangIgnoreMultiGroups._category = "守望🐢/工具";
app.registerExtension({
    name: "ShouWang.FastGroupsBypasser",
    registerCustomNodes() {
        ShouWangIgnoreMultiGroups.setUp();
    },
    beforeRegisterVueAppNodeDefs(defs) {
        const def = defs.find((d) => d.name === NodeTypesString.FAST_GROUPS_BYPASSER);
        if (def) {
            def.display_name = "守望-忽略多组🐢";
            def.category = "守望🐢/工具";
        }
    },
    loadedGraphNode(node) {
        if (node.type == ShouWangIgnoreMultiGroups.type) {
            node.tempSize = [...node.size];
        }
    },
});
