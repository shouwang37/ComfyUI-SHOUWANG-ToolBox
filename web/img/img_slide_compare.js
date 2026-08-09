/**
 * ComfyUI-SHOUWANG-ToolBox — 图像滑动对比节点前端扩展
 *
 * 参考 rgthree-comfy 的 Image Comparer（忽略多组选择 / 禁用 / 书签等附加功能）：
 *   - 接收图像A / 图像B，节点内画布展示
 *   - 鼠标悬停节点并左右移动：分割线左侧显示图像B，右侧显示图像A
 *   - 仅取每组第一张图像展示
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_TYPE = "ShouWangImageSlideCompare";
const DEFAULT_SIZE = [192, 144]; // 节点默认画布尺寸

/** 由后端返回的图像数据构造预览 URL */
const imageDataToUrl = (data) => api.apiURL(
    `/view?filename=${encodeURIComponent(data.filename)}&type=${data.type}&subfolder=${data.subfolder}${app.getPreviewFormatParam()}${app.getRandParam()}`,
);

/** 图像对比画布 widget：绘制两张图像并响应鼠标滑动分割 */
class ImageSlideCompareWidget {
    constructor(name, node) {
        this.name = name;
        this.type = "custom";
        this.node = node;
        this.images = []; // [{ name, url, img }]，A 在 0 位，B 在 1 位
        this._value = { images: [] };
    }

    get value() {
        return this._value;
    }

    set value(v) {
        const cleaned = (v.images || []).map((d) => {
            if (!d.img) {
                d.img = new Image();
                d.img.src = d.url;
            }
            return d;
        });
        this._value.images = cleaned;
        this.images = cleaned;
    }

    draw(ctx, node, width, y) {
        const [imageA, imageB] = this.images;
        // 先绘制图像A全图，悬停时按鼠标 x 位置裁剪绘制图像B，形成滑动对比
        this.drawImage(ctx, imageA, y);
        if (node.isPointerOver && imageB) {
            this.drawImage(ctx, imageB, y, node.pointerOverPos[0]);
        }
    }

    drawImage(ctx, image, y, cropX) {
        const img = image?.img;
        if (!img?.naturalWidth || !img?.naturalHeight) return;

        const [nodeWidth, nodeHeight] = this.node.size;
        const height = nodeHeight - y;
        const imageAspect = img.naturalWidth / img.naturalHeight;
        const widgetAspect = nodeWidth / height;

        // 按节点宽高比缩放图像（contain），不足的宽度水平居中
        let targetWidth;
        let targetHeight;
        let offsetX = 0;
        if (imageAspect > widgetAspect) {
            targetWidth = nodeWidth;
            targetHeight = nodeWidth / imageAspect;
        } else {
            targetHeight = height;
            targetWidth = height * imageAspect;
            offsetX = (nodeWidth - targetWidth) / 2;
        }

        const widthMultiplier = img.naturalWidth / targetWidth;
        const sourceWidth = cropX != null ? (cropX - offsetX) * widthMultiplier : img.naturalWidth;
        const destX = (nodeWidth - targetWidth) / 2;
        const destY = y + (height - targetHeight) / 2;
        const destWidth = cropX != null ? cropX - offsetX : targetWidth;
        const destHeight = targetHeight;

        ctx.save();
        ctx.beginPath();
        const globalCompositeOperation = ctx.globalCompositeOperation;
        if (cropX != null) {
            ctx.rect(destX, destY, destWidth, destHeight);
            ctx.clip();
        }
        ctx.drawImage(img, 0, 0, sourceWidth, img.naturalHeight, destX, destY, destWidth, destHeight);
        // 分割线（仅绘制在图像有效显示范围内）
        if (cropX != null && cropX >= (nodeWidth - targetWidth) / 2 && cropX <= targetWidth + offsetX) {
            ctx.beginPath();
            ctx.moveTo(cropX, destY);
            ctx.lineTo(cropX, destY + destHeight);
            ctx.globalCompositeOperation = "difference";
            ctx.strokeStyle = "rgba(255,255,255, 1)";
            ctx.stroke();
        }
        ctx.globalCompositeOperation = globalCompositeOperation;
        ctx.restore();
    }

    computeSize(width) {
        return [width, 20];
    }

    serializeValue() {
        return {
            images: this.images.map(({ img, ...rest }) => rest),
        };
    }
}

app.registerExtension({
    name: "SHOUWANG.ImageSlideCompare",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        // ── 节点创建：初始化画布 widget 与交互状态 ──
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            this.isPointerOver = false;
            this.pointerOverPos = [0, 0];
            this.canvasWidget = this.addCustomWidget(new ImageSlideCompareWidget("shouwang_compare", this));
            this.setSize([...DEFAULT_SIZE]);
            this.setDirtyCanvas(true, true);
        };

        // ── 执行完成：接收后端返回的两组图像并刷新画布 ──
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (output) {
            onExecuted?.apply(this, arguments);

            const images = [];
            if (output.a_images?.[0]) images.push({ name: "A", url: imageDataToUrl(output.a_images[0]) });
            if (output.b_images?.[0]) images.push({ name: "B", url: imageDataToUrl(output.b_images[0]) });
            this.canvasWidget.value = { images };
            this.setDirtyCanvas(true, true);
        };

        // ── 鼠标交互：悬停/移动驱动滑动对比 ──
        const onMouseEnter = nodeType.prototype.onMouseEnter;
        nodeType.prototype.onMouseEnter = function (event) {
            const result = onMouseEnter?.apply(this, arguments);
            this.isPointerOver = true;
            this.setDirtyCanvas(true, false);
            return result;
        };

        const onMouseLeave = nodeType.prototype.onMouseLeave;
        nodeType.prototype.onMouseLeave = function (event) {
            const result = onMouseLeave?.apply(this, arguments);
            this.isPointerOver = false;
            this.setDirtyCanvas(true, false);
            return result;
        };

        const onMouseMove = nodeType.prototype.onMouseMove;
        nodeType.prototype.onMouseMove = function (event, pos, canvas) {
            const result = onMouseMove?.apply(this, arguments);
            this.pointerOverPos = [pos[0], pos[1]];
            this.setDirtyCanvas(true, false);
            return result;
        };
    },
});
