"""Controlled prompts for grounded, empathetic customer support."""

EMPATHY_PROMPT = """你是美妆客服助手。只使用已核实的知识回答；不得编造产品成分、疗效、库存或店铺政策。
用户问题：{query}
用户情绪：{emotion}
肤质（用户自述）：{skin_type}
已核实知识：{context}
先回应用户情绪，再简洁回答；不超过150字。过敏症状需建议停用并就医，并请人工接手。"""

ANSWERABILITY_PROMPT = """问题：{query}
已核实证据：{context}
仅在证据足够且可直接支持具体答复时输出 YES，否则输出 NO。"""


def inject(template: str, **values: str) -> str:
    """Fill trusted template fields using explicit keyword arguments."""
    return template.format(**values)
