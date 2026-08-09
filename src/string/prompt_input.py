class text_input:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "text_multiline"
    OUTPUT_IS_LIST = (False,)

    CATEGORY = "守望🐢/提示词"

    def text_multiline(self, text):
        new_text = []
        lines = text.split('\n')
        for line in lines:
            if not line.strip().startswith('#'):
                new_text.append(line)
        result = '\n'.join(new_text)
        return (result,)


NODE_CLASS_MAPPINGS = {
    "ShouWangTextInput": text_input,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ShouWangTextInput": "守望-提示词输入🐢",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

