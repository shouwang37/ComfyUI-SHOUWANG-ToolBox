class PromptTaggerBatchNode:
    """守望-Tagger批量反推器：配置本地文件夹的批量打标参数，输出「批量打标」配置数据。

    连接到「守望-Tagger反推器🐢」节点的「批量打标」输入口后，
    反推器节点以所选模型对整个文件夹的图片批量反推并保存 Tag 文件。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图片文件夹地址": ("STRING", {"default": ""}),
                "打标格式": (["txt"], {"default": "txt"}),
                "附加提示词": ("STRING", {"default": "", "multiline": True}),
                "递归搜索子文件夹": ("BOOLEAN", {"default": False}),
                "已存在Tag文件": (["忽略", "覆盖"], {"default": "忽略"}),
            }
        }

    RETURN_TYPES = ("TAGGER_BATCH",)
    RETURN_NAMES = ("批量打标输出",)
    FUNCTION = "run"
    CATEGORY = "守望🐢/提示词"

    def run(self, 图片文件夹地址, 打标格式, 附加提示词, 递归搜索子文件夹, 已存在Tag文件):
        config = {
            "folder": 图片文件夹地址.strip(),
            "format": 打标格式,
            "extra_prompt": 附加提示词,
            "recursive": 递归搜索子文件夹,
            "exists": 已存在Tag文件,
        }
        return (config,)


NODE_CLASS_MAPPINGS = {
    "prompt_tagger_Batch": PromptTaggerBatchNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "prompt_tagger_Batch": "守望-Tagger批量反推器🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
