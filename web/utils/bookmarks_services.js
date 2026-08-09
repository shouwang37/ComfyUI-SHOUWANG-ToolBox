import { app } from "/scripts/app.js";
import { reduceNodesDepthFirst } from "./utils.js";

const SHORTCUT_DEFAULTS = "1234567890abcdefghijklmnopqrstuvwxyz".split("");
const BOOKMARK_NODE_TYPE = "ShouWangBookmark";

class BookmarksService {
    /**
     * 获取当前工作流（含子图）中的所有书签节点。
     */
    getCurrentBookmarks() {
        return reduceNodesDepthFirst(
            app.graph.nodes,
            (n, acc) => {
                if (n.type === BOOKMARK_NODE_TYPE) {
                    acc.push(n);
                }
            },
            [],
        ).sort((a, b) => a.title.localeCompare(b.title));
    }

    getExistingShortcuts() {
        const bookmarkNodes = this.getCurrentBookmarks();
        const usedShortcuts = new Set(bookmarkNodes.map((n) => n.shortcutKey));
        return usedShortcuts;
    }

    /** 为新建书签分配下一个未占用的默认快捷键（1-9、0、a-z） */
    getNextShortcut() {
        const existingShortcuts = this.getExistingShortcuts();
        return SHORTCUT_DEFAULTS.find((char) => !existingShortcuts.has(char)) ?? "1";
    }
}

/** The BookmarksService singleton. */
export const SERVICE = new BookmarksService();
