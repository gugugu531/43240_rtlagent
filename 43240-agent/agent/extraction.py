"""Extract RTL source from model replies.

This is deliberately separate from llm.py: transport errors and response-shape
handling belong to the model client, while deciding which text is Verilog belongs
to the agent. The first version preserves the example agent's extraction policy.
"""

from __future__ import annotations

import re


def extract_code(text: str) -> str:
    """Pull the Verilog out of a model reply."""
    blocks = re.findall(
        r"```(?:systemverilog|verilog|sv|v|)\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        # 取最长的代码块：模型常先回显接口。
        return max(blocks, key=len).strip() + "\n"

    # 无代码围栏时，若整体形似代码则全部取用。
    if "module" in text and "endmodule" in text:
        return text.strip() + "\n"

    return ""
