// rgthree.js —— 最小替代版（搬运自 rgthree-comfy web/comfyui/rgthree.js 的日志部分）
// 原版 rgthree.js 是整个 rgthree-comfy 的运行时（书签/进度条/上下文菜单/配置面板等全局副作用），
// 此处仅保留 base_node.js 实际使用的 LogLevel / Logger / LogSession / invokeExtensionsAsync，
// 其余逻辑与全局注入均不搬运。
import { app } from "/scripts/app.js";
export var LogLevel;
(function (LogLevel) {
    LogLevel[LogLevel["IMPORTANT"] = 1] = "IMPORTANT";
    LogLevel[LogLevel["ERROR"] = 2] = "ERROR";
    LogLevel[LogLevel["WARN"] = 3] = "WARN";
    LogLevel[LogLevel["INFO"] = 4] = "INFO";
    LogLevel[LogLevel["DEBUG"] = 5] = "DEBUG";
    LogLevel[LogLevel["DEV"] = 6] = "DEV";
})(LogLevel || (LogLevel = {}));
const LogLevelToMethod = {
    [LogLevel.IMPORTANT]: "log",
    [LogLevel.ERROR]: "error",
    [LogLevel.WARN]: "warn",
    [LogLevel.INFO]: "info",
    [LogLevel.DEBUG]: "log",
    [LogLevel.DEV]: "log",
};
const LogLevelToCSS = {
    [LogLevel.IMPORTANT]: "font-weight: bold; color: blue;",
    [LogLevel.ERROR]: "",
    [LogLevel.WARN]: "",
    [LogLevel.INFO]: "font-style: italic; color: blue;",
    [LogLevel.DEBUG]: "font-style: italic; color: #444;",
    [LogLevel.DEV]: "color: #004b68;",
};
let GLOBAL_LOG_LEVEL = LogLevel.ERROR;
const INVOKE_EXTENSIONS_BLOCKLIST = [
    {
        name: "Comfy.WidgetInputs",
        reason: "Major conflict with rgthree-comfy nodes' inputs causing instability and " +
            "repeated link disconnections.",
    },
    {
        name: "efficiency.widgethider",
        reason: "Overrides value getter before widget getter is prepared. Can be lifted if/when " +
            "https://github.com/jags111/efficiency-nodes-comfyui/pull/203 is pulled.",
    },
];
class Logger {
    log(level, message, ...args) {
        var _a;
        const [n, v] = this.logParts(level, message, ...args);
        (_a = console[n]) === null || _a === void 0 ? void 0 : _a.call(console, ...v);
    }
    logParts(level, message, ...args) {
        if (level <= GLOBAL_LOG_LEVEL) {
            const css = LogLevelToCSS[level] || "";
            if (level === LogLevel.DEV) {
                message = `🔧 ${message}`;
            }
            return [LogLevelToMethod[level], [`%c${message}`, css, ...args]];
        }
        return ["none", []];
    }
}
class LogSession {
    constructor(name) {
        this.name = name;
        this.logger = new Logger();
        this.logsCache = {};
    }
    logParts(level, message, ...args) {
        message = `${this.name || ""}${message ? " " + message : ""}`;
        return this.logger.logParts(level, message, ...args);
    }
    logPartsOnceForTime(level, time, message, ...args) {
        message = `${this.name || ""}${message ? " " + message : ""}`;
        const cacheKey = `${level}:${message}`;
        const cacheEntry = this.logsCache[cacheKey];
        const now = +new Date();
        if (cacheEntry && cacheEntry.lastShownTime + time > now) {
            return ["none", []];
        }
        const parts = this.logger.logParts(level, message, ...args);
        if (console[parts[0]]) {
            this.logsCache[cacheKey] = this.logsCache[cacheKey] || {};
            this.logsCache[cacheKey].lastShownTime = now;
        }
        return parts;
    }
    debugParts(message, ...args) {
        return this.logParts(LogLevel.DEBUG, message, ...args);
    }
    infoParts(message, ...args) {
        return this.logParts(LogLevel.INFO, message, ...args);
    }
    warnParts(message, ...args) {
        return this.logParts(LogLevel.WARN, message, ...args);
    }
    errorParts(message, ...args) {
        return this.logParts(LogLevel.ERROR, message, ...args);
    }
    newSession(name) {
        return new LogSession(`${this.name}${name}`);
    }
}
class Rgthree extends EventTarget {
    constructor() {
        super();
        this.version = "1.0.0";
        this.logger = new LogSession("[rgthree]");
    }
    logParts(level, message, ...args) {
        return this.logger.logParts(level, message, ...args);
    }
    isDebugMode() {
        return GLOBAL_LOG_LEVEL >= LogLevel.DEBUG;
    }
    isDevMode() {
        return GLOBAL_LOG_LEVEL >= LogLevel.DEV;
    }
    async invokeExtensionsAsync(method, ...args) {
        var _a;
        return await Promise.all(app.extensions.map(async (ext) => {
            var _a, _b;
            if (ext === null || ext === void 0 ? void 0 : ext[method]) {
                try {
                    const blocked = INVOKE_EXTENSIONS_BLOCKLIST.find((block) => ext.name.toLowerCase().startsWith(block.name.toLowerCase()));
                    if (blocked) {
                        const [n, v] = this.logger.logPartsOnceForTime(LogLevel.WARN, 5000, `Blocked extension '${ext.name}' method '${method}' for rgthree-nodes because: ${blocked.reason}`);
                        (_a = console[n]) === null || _a === void 0 ? void 0 : _a.call(console, ...v);
                        return Promise.resolve();
                    }
                    return await ext[method](...args, app);
                }
                catch (error) {
                    const [n, v] = this.logParts(LogLevel.ERROR, `Error calling extension '${ext.name}' method '${method}' for rgthree-node.`, { error }, { extension: ext }, { args });
                    (_b = console[n]) === null || _b === void 0 ? void 0 : _b.call(console, ...v);
                }
            }
        }));
    }
}
export const rgthree = new Rgthree();
