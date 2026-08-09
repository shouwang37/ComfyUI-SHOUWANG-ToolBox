import { app } from "/scripts/app.js";
import { RgthreeHelpDialog } from "./dialog.js";
export function addMenuItemOnExtraMenuOptions(node, config, menuOptions, after = "Shape") {
    let idx = menuOptions
        .slice()
        .reverse()
        .findIndex((option) => option === null || option === void 0 ? void 0 : option.isRgthree);
    if (idx == -1) {
        idx = menuOptions.findIndex((option) => { var _a; return (_a = option === null || option === void 0 ? void 0 : option.content) === null || _a === void 0 ? void 0 : _a.includes(after); }) + 1;
        if (!idx) {
            idx = menuOptions.length - 1;
        }
        menuOptions.splice(idx, 0, null);
        idx++;
    }
    else {
        idx = menuOptions.length - idx;
    }
    const subMenuOptions = typeof config.subMenuOptions === "function"
        ? config.subMenuOptions(node)
        : config.subMenuOptions;
    menuOptions.splice(idx, 0, {
        content: typeof config.name == "function" ? config.name(node) : config.name,
        has_submenu: !!(subMenuOptions === null || subMenuOptions === void 0 ? void 0 : subMenuOptions.length),
        isRgthree: true,
        callback: (value, _options, event, parentMenu, _node) => {
            if (!!(subMenuOptions === null || subMenuOptions === void 0 ? void 0 : subMenuOptions.length)) {
                new LiteGraph.ContextMenu(subMenuOptions.map((option) => (option ? { content: option } : null)), {
                    event,
                    parentMenu,
                    callback: (subValue, _options, _event, _parentMenu, _node) => {
                        if (config.property) {
                            node.properties = node.properties || {};
                            node.properties[config.property] = config.prepareValue
                                ? config.prepareValue(subValue.content || "", node)
                                : subValue.content || "";
                        }
                        config.callback && config.callback(node, subValue === null || subValue === void 0 ? void 0 : subValue.content);
                    },
                });
                return;
            }
            if (config.property) {
                node.properties = node.properties || {};
                node.properties[config.property] = config.prepareValue
                    ? config.prepareValue(node.properties[config.property], node)
                    : !node.properties[config.property];
            }
            config.callback && config.callback(node, value === null || value === void 0 ? void 0 : value.content);
        },
    });
}
export function addHelpMenuItem(node, content, menuOptions) {
    addMenuItemOnExtraMenuOptions(node, {
        name: "🛟 Node Help",
        callback: (node) => {
            if (node.showHelp) {
                node.showHelp();
            }
            else {
                new RgthreeHelpDialog(node, content).show();
            }
        },
    }, menuOptions, "Properties Panel");
}
export function findFromNodeForSubgraph(subgraphId) {
    var _a;
    const node = (_a = findSomethingInAllSubgraphs((subgraph) => subgraph.nodes
        .filter((node) => node.isSubgraphNode())
        .find((node) => node.subgraph.id === subgraphId))) !== null && _a !== void 0 ? _a : null;
    return node;
}
function findSomethingInAllSubgraphs(fn) {
    var _a, _b;
    const rootGraph = (_a = app.rootGraph) !== null && _a !== void 0 ? _a : app.graph.rootGraph;
    const subgraphs = [rootGraph, ...(_b = rootGraph.subgraphs) === null || _b === void 0 ? void 0 : _b.values()];
    for (const subgraph of subgraphs) {
        const thing = fn(subgraph);
        if (thing)
            return thing;
    }
    return null;
}
export function changeModeOfNodes(nodeOrNodes, mode) {
    reduceNodesDepthFirst(nodeOrNodes, (n) => {
        n.mode = mode;
    });
}
export function reduceNodesDepthFirst(nodeOrNodes, reduceFn, reduceTo) {
    var _a;
    const nodes = Array.isArray(nodeOrNodes) ? nodeOrNodes : [nodeOrNodes];
    const stack = nodes.map((node) => ({ node }));
    while (stack.length > 0) {
        const { node } = stack.pop();
        const result = reduceFn(node, reduceTo);
        if (result !== undefined && result !== reduceTo) {
            reduceTo = result;
        }
        if (((_a = node.isSubgraphNode) === null || _a === void 0 ? void 0 : _a.call(node)) && node.subgraph) {
            const children = node.subgraph.nodes;
            for (let i = children.length - 1; i >= 0; i--) {
                stack.push({ node: children[i] });
            }
        }
    }
    return reduceTo;
}
export function getGroupNodes(group) {
    return Array.from(group._children).filter((c) => c instanceof LGraphNode);
}
export function getGraphDependantNodeKey(node) {
    var _a;
    const graph = (_a = node.graph) !== null && _a !== void 0 ? _a : app.graph;
    return `${graph.id}:${node.id}`;
}
