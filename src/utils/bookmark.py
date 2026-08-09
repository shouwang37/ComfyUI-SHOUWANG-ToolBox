# 守望-书签节点（参考 rgthree-comfy 的 Bookmark 节点）
# 纯标记用途：可放置在工作流任意位置，设定快捷键后按下即可跳转到书签位置（节点左上角）并应用缩放
# 前端 web/bookmark.js 会覆写此节点的实现为书签交互（快捷键录入、画布跳转、🔖 标题、无端口）


class ShouWangBookmark:
    """守望-书签🐢：工作流书签标记节点，按快捷键跳转到书签位置（参考 rgthree Bookmark）"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    RETURN_NAMES = ()
    FUNCTION = "noop"
    CATEGORY = "守望🐢/工具"

    def noop(self):
        return ()


NODE_CLASS_MAPPINGS = {"ShouWangBookmark": ShouWangBookmark}
NODE_DISPLAY_NAME_MAPPINGS = {"ShouWangBookmark": "守望-书签🐢"}
