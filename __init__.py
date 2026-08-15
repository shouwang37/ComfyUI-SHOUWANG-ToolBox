# 导入各个模块以确保节点注册
import os
import sys

# Web 扩展目录（JS 级联菜单）
WEB_DIRECTORY = "./web"

# ═══ 背景壁纸本地文件代理路由 ═══
# 浏览器安全限制：<img> 无法直接加载本地磁盘路径（E:\... 不是可访问 URL），
# 前端（settings.js toWallpaperUrl）检测到本地路径时自动转换为本路由 URL，
# 由后端读取本地图片并以 HTTP 响应返回（仅限图片扩展名，配合 isfile 校验）。
try:
    from server import PromptServer
    from aiohttp import web

    _WALLPAPER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}

    def _setup_wallpaper_route():
        # PromptServer.instance 需用 getattr 安全访问（不同版本实例化时机不同）
        server = getattr(PromptServer, "instance", None)
        if server is None:
            print("[ShouwangToolBox] PromptServer.instance 不可用，壁纸代理路由未注册")
            return

        @server.routes.get("/shouwang/wallpaper")
        async def wallpaper(request):
            path = request.query.get("path", "")
            if not path or os.path.splitext(path)[1].lower() not in _WALLPAPER_EXTS:
                return web.Response(status=400, text="invalid wallpaper path")
            if not os.path.isfile(path):
                return web.Response(status=404, text="wallpaper not found")
            return web.FileResponse(path)

    _setup_wallpaper_route()
except Exception as e:
    print(f"[ShouwangToolBox] 壁纸代理路由注册失败: {e}")


# 确保当前目录在Python路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 导入 src 子目录下的各功能模块
# 模块按功能划分：string（文本/标签）、image（图像处理）、sampler（采样器）、utils（工具）、audio（音频）
try:
    import src.string.prompt_tagger
    import src.string.prompt_tagger_Batch
    import src.string.prompt_input
    import src.string.prompt_replacer
    import src.string.prompt_filter
    import src.string.prompt_merger
    import src.string.prompt_formatter
    import src.string.lsnet_artist_inference
    import src.utils.anything_select
    import src.utils.save_to_folder
    import src.utils.load_from_folder
    import src.utils.show_anything
    import src.utils.color_picker
    import src.utils.outpaint_canvas
    import src.utils.bookmark
    import src.sampler.Partial_repainting
    import src.sampler.usdu_upscale
    import src.model.lsnet_model_loader
    import src.image.img_paste_load
    import src.image.img_splice
    import src.image.img_crop
    import src.image.img_side_scaling
    import src.image.img_slide_compare
    import src.image.img_splice_comparison
    import src.image.img_tile_size
    import src.image.img_tile_batch
    import src.image.img_tile_assemble
    import src.image.img_format
    import src.audio.play_audio

    # 合并所有模块的节点映射
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

    # 从各个模块收集节点映射
    modules = [src.string.prompt_tagger, src.string.prompt_tagger_Batch, src.string.prompt_input, src.string.prompt_replacer, src.string.prompt_filter, src.string.prompt_merger, src.string.prompt_formatter, src.string.lsnet_artist_inference, src.utils.anything_select, src.utils.save_to_folder, src.utils.load_from_folder, src.utils.show_anything, src.utils.color_picker, src.utils.outpaint_canvas, src.utils.bookmark, src.sampler.Partial_repainting, src.sampler.usdu_upscale, src.model.lsnet_model_loader, src.image.img_paste_load, src.image.img_splice, src.image.img_crop, src.image.img_side_scaling, src.image.img_slide_compare, src.image.img_splice_comparison, src.image.img_tile_size, src.image.img_tile_batch, src.image.img_tile_assemble, src.image.img_format, src.audio.play_audio]
    for module in modules:
        if hasattr(module, 'NODE_CLASS_MAPPINGS'):
            NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
        if hasattr(module, 'NODE_DISPLAY_NAME_MAPPINGS'):
            NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)
    
    __all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
except Exception as e:
    import traceback
    print(f"Error importing modules: {e}")
    traceback.print_exc()