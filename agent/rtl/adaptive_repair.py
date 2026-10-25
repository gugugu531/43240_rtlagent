"""One combined attribution/complete-RTL response; never a format retry."""

import json
import re
from agent.llm.structured import strict_json
from agent.rtl.extract import extract_result


def repair_request(task, parent, evidence, checker=None):
    public = {"prompt": task.prompt, "interface": task.interface, "top": task.top}
    return [
        {"role": "system", "content": (
            "你是数字前端工程师。基于完整公开题面、当前RTL和实际工具证据，一次完成归因与必要修复。"
            "检查器也可能错误；不为迎合检查器修改题目语义。只修复明确的RTL错误，保留正确行为。"
            "只输出一个json代码块，字段严格为 decision 和 reason。decision仅为rtl_error、checker_suspect、"
            "spec_unclear；reason给出具体根因。仅rtl_error时，随后输出一个verilog代码块，包含完整可综合文件。"
            "不输出其他正文、测试台、补丁或省略代码，不新增题面未规定的复位/接口。"
            "时序用非阻塞赋值，组合赋默认值，严格保持时钟、复位、优先级、宽度、signed和周期行为。"
            "编译/综合错误须核对所有独立根因和写入者，不能只消除日志文本。"
        )},
        {"role": "user", "content": json.dumps({
            "public_task": public, "candidate": {"id": parent.id, "hash": parent.code_hash, "rtl": parent.code},
            "evidence": evidence,
            "checker": checker.public_dict() if checker else None,
        }, ensure_ascii=False)},
    ]


def parse_repair(text, top, *, finish_reason=None):
    if finish_reason == "length":
        raise ValueError("combined repair response was truncated")
    if not isinstance(text, str) or len(text.encode()) > 524288:
        raise ValueError("invalid combined repair response size")
    match = re.fullmatch(
        r"\s*```json\s*\n(.*?)\n```\s*(?:```(?:verilog|systemverilog|sv)\s*\n(.*?)\n```\s*)?",
        text, re.DOTALL,
    )
    if not match:
        raise ValueError("repair requires one JSON decision and an optional complete RTL block")
    try:
        decision = strict_json(match.group(1))
    except RecursionError as error:
        raise ValueError("repair decision JSON nesting exceeds the parser limit") from error
    if (not isinstance(decision, dict) or set(decision) != {"decision", "reason"}
            or decision["decision"] not in {"rtl_error", "checker_suspect", "spec_unclear"}
            or not isinstance(decision["reason"], str) or not decision["reason"].strip()):
        raise ValueError("invalid repair attribution")
    code = match.group(2)
    if (decision["decision"] == "rtl_error") != (code is not None):
        raise ValueError("only attributed RTL errors may contain a replacement")
    extraction = extract_result(f"```verilog\n{code}\n```", top) if code is not None else None
    if extraction and (extraction.status != "ok" or not extraction.complete or not extraction.target_module_found):
        raise ValueError("repair did not contain one complete target implementation")
    return decision, extraction
