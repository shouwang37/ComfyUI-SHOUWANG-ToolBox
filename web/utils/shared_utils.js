export function wait(ms = 16) {
    if (ms === 16) {
        return new Promise((resolve) => {
            requestAnimationFrame(() => {
                resolve();
            });
        });
    }
    return new Promise((resolve) => {
        setTimeout(() => {
            resolve();
        }, ms);
    });
}
export function moveArrayItem(arr, itemOrFrom, to) {
    const from = typeof itemOrFrom === "number" ? itemOrFrom : arr.indexOf(itemOrFrom);
    arr.splice(to, 0, arr.splice(from, 1)[0]);
}
export function defineProperty(instance, property, desc) {
    var _a, _b, _c, _d, _e, _f;
    const existingDesc = Object.getOwnPropertyDescriptor(instance, property);
    if ((existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.configurable) === false) {
        throw new Error(`Error: rgthree-comfy cannot define un-configurable property "${property}"`);
    }
    if ((existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.get) && desc.get) {
        const descGet = desc.get;
        desc.get = () => {
            existingDesc.get.apply(instance, []);
            return descGet.apply(instance, []);
        };
    }
    if ((existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.set) && desc.set) {
        const descSet = desc.set;
        desc.set = (v) => {
            existingDesc.set.apply(instance, [v]);
            return descSet.apply(instance, [v]);
        };
    }
    desc.enumerable = (_b = (_a = desc.enumerable) !== null && _a !== void 0 ? _a : existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.enumerable) !== null && _b !== void 0 ? _b : true;
    desc.configurable = (_d = (_c = desc.configurable) !== null && _c !== void 0 ? _c : existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.configurable) !== null && _d !== void 0 ? _d : true;
    if (!desc.get && !desc.set) {
        desc.writable = (_f = (_e = desc.writable) !== null && _e !== void 0 ? _e : existingDesc === null || existingDesc === void 0 ? void 0 : existingDesc.writable) !== null && _f !== void 0 ? _f : true;
    }
    return Object.defineProperty(instance, property, desc);
}
