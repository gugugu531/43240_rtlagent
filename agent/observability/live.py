"""Opt-in, public JSONL projection of one Burr run."""

from functools import wraps
import json
import os
import re
import stat
import time

from agent.observability.redaction import ENV_SECRETS, SENSITIVE, Redactor
from agent.runtime.budget import BudgetExhausted, Deadline


def best_effort(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (BudgetExhausted, Deadline):
            # The solver's signal handler can interrupt any Python instruction.
            raise
        except Exception:
            # Display formatting and disk failures must not affect the answer.
            return None
    return guarded


_PRIVATE_KEYS = SENSITIVE | {
    "path", "paths", "cwd", "command", "commands", "argv", "environment", "env",
    "config", "settings", "configuration", "headers", "url", "endpoint",
    "payload", "request", "response", "messages", "prompt", "reasoning",
    "reasoning_content", "thinking", "analysis", "chain_of_thought",
    "host", "hostname", "workdir", "credentials", "stdout", "stderr", "raw_response", "raw_request",
}
_CREDENTIAL = re.compile(
    r"""(?ix)\b(?:authorization|(?:set[-_])?cookie|(?:api[-_]?key|password|secret|token)|
    [\w]+_(?:token|key|password|secret|cookie))["']?\s*[:=]\s*
    (?:(?:bearer|basic)\s+)?(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)"""
)
_HEADER = re.compile(r"(?im)\b(?:(?:proxy-)?authorization|(?:set-)?cookie)\s*:\s*[^\r\n]+")
_HOST_SETTING = re.compile(
    r"""(?i)\b(?:RTLAGENT_|FPGACHINA_|LLM_|AGENT_)[A-Z0-9_]+["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)"""
)
_AUTH_TOKEN = re.compile(r"(?i)\bbearer\s+[\w~+./=-]+")
_PRIVATE_THOUGHT = re.compile(r"<(think|thinking|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|\Z)", re.I | re.S)
_URL = re.compile(r"""(?i)\b(?:https?|file|ssh)://[^\s"'<>]+""")
# Match host paths at word boundaries. Division, comments and escaped Verilog
# identifiers in source code are handled separately from diagnostic prose.
_PATH_START = r"(?:/(?![/\s])|\.\.?/|~/|[A-Za-z]:[\\/]|\\\\[\w.-]+[\\/])"
_QUOTED_PATH = re.compile(r"""(["'])""" + _PATH_START + r""".*?\1""")
_BRACKETED_PATH = re.compile(r"\[" + _PATH_START + r"[^\]\n]+\]")
_PATH = re.compile(r"""(?<![\w$./])""" + _PATH_START + r"""[^\s"'<>()[\]{},;]+""")
_RELATIVE_FILE = re.compile(
    r"""(?<![\w$./])(?:[\w.-]+[/\\])+[\w.-]+\.[\w-]+(?=$|[\s:"'<>()\[\]{},;])"""
)
_CODE_TEXT = re.compile(r"""//[^\n]*|/\*.*?(?:\*/|\Z)|"(?:\\.|[^"\\])*" """, re.S | re.X)
_ENV_NAME = re.compile(r"\b(?:" + "|".join(map(re.escape, ENV_SECRETS)) + r")\b", re.I)
_SIGNAL_VALUE = re.compile(r"""(?i)(?:token|secret|password)\s*=\s*(?:[a-z0-9_$][\w$'.\[\]:/+*~&|^-]*|'[01xz])\Z""")
_RTL_START = re.compile(r"(?im)(?P<fence>^[ \t]*\x60{3}(?:verilog|systemverilog|sv)\b)|\bmodule\s+[\w$]+(?=\s*[#(;])")
_END_FENCE = re.compile(r"(?m)^[ \t]*\x60{3}[ \t]*\r?$")
_END_MODULE = re.compile(r"\bendmodule\b")


def _rtl_credential(match):
    return match.group() if _SIGNAL_VALUE.fullmatch(match.group()) else "[凭据已隐藏]"


def _reasoning_path(match):
    # In a native text field the slash in a closing tag is part of the model's text.
    if (match.string[match.start() - 1:match.start()] == "<"
            and match.group().lower() in {"/think", "/thinking", "/analysis", "/reasoning"}
            and match.string[match.end():match.end() + 1] == ">"):
        return match.group()
    return "[路径已隐藏]"


def _rtl_path(match):
    # Comments and strings have already gone through the prose filter.
    # In an expression such as "a /b" the slash is division.
    if re.fullmatch(r"/[\w$.]+", match.group()):
        left = match.start() - 1
        while left >= 0 and match.string[left] in " \t":
            left -= 1
        if left >= 0 and (match.string[left].isalnum() or match.string[left] in "_$)]"):
            return match.group()
    return _reasoning_path(match)


def public_text(value, *, rtl=False, native_reasoning=False):
    if not native_reasoning:
        value = _PRIVATE_THOUGHT.sub("[私有内容已隐藏]", value)
    if rtl:
        value = _CODE_TEXT.sub(code_text, value)
    value = _HEADER.sub("[凭据已隐藏]", value)
    value = _HOST_SETTING.sub("[宿主配置已隐藏]", value)
    value = _CREDENTIAL.sub(_rtl_credential if rtl else "[凭据已隐藏]", value)
    value = _AUTH_TOKEN.sub("[凭据已隐藏]", value)
    value = _ENV_NAME.sub("[凭据已隐藏]", value)
    value = _URL.sub("[地址已隐藏]", value)
    value = _QUOTED_PATH.sub("[路径已隐藏]", value)
    value = _BRACKETED_PATH.sub("[路径已隐藏]", value)
    path = _rtl_path if rtl else _reasoning_path if native_reasoning else "[路径已隐藏]"
    value = _PATH.sub(path, value)
    return _RELATIVE_FILE.sub("[路径已隐藏]", value)


def model_text(value, native_reasoning):
    if not native_reasoning:
        value = _PRIVATE_THOUGHT.sub("[私有内容已隐藏]", value)
    parts = []
    pos = 0
    while start := _RTL_START.search(value, pos):
        boundary = _END_FENCE if start["fence"] else _END_MODULE
        end = boundary.search(value, start.end())
        stop = end.end() if end else len(value)
        parts.append(public_text(value[pos:start.start()], native_reasoning=native_reasoning))
        parts.append(public_text(value[start.start():stop], rtl=True, native_reasoning=native_reasoning))
        pos = stop
    parts.append(public_text(value[pos:], native_reasoning=native_reasoning))
    return "".join(parts)


def code_text(match):
    text = match.group()
    if text.startswith("//"):
        return "//" + public_text(text[2:])
    if text.startswith("/*"):
        if text.endswith("*/"):
            return "/*" + public_text(text[2:-2]) + "*/"
        return "/*" + public_text(text[2:])
    return '"' + public_text(text[1:-1]) + '"'


def fields(source, *keys):
    return {key: source[key] for key in keys if key in source}


class LiveEvents:
    def __init__(self, stream, secrets):
        from .live_rtl import RtlEvidence

        self.stream = stream
        self.secrets = secrets  # The recorder also discovers credentials in structured evidence.
        self._tool_secrets = Redactor()
        self.nodes = {}
        self.current = self.previous = None
        self.visits = 0
        self.rtl = RtlEvidence(self.detail)

    @classmethod
    @best_effort
    def open(cls, directory, secrets):
        # Do not follow a pre-existing link or wait for a reader on a FIFO.
        flags = os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW
        fd = os.open(directory / "live.jsonl", flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return None
            os.ftruncate(fd, 0)
            stream = os.fdopen(fd, "w", encoding="utf-8", errors="backslashreplace")
            fd = None
            return cls(stream, secrets)
        finally:
            if fd is not None:
                os.close(fd)

    def _text(self, value, *, code=False, model=False, native_reasoning=False):
        value = value.encode("utf-8", errors="backslashreplace").decode("utf-8")
        for secret in sorted(self._tool_secrets.secrets.union(self.secrets), key=len, reverse=True):
            value = value.replace(secret, "[凭据已隐藏]")
        if code:
            # Keep operators, directives and identifiers such as 'token' intact.
            value = _PRIVATE_THOUGHT.sub("[私有内容已隐藏]", value)
            return _CODE_TEXT.sub(code_text, value)
        return model_text(value, native_reasoning) if model else public_text(value)

    def _public(self, value, parent=""):
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, list):
            return [self._public(item, parent) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                key = str(key)
                name = key.lower().replace("-", "_")
                # Ports in a typed stimulus or comparison can be named "token".
                signal = parent in {"inputs", "ports", "values", "expected", "pre_expected", "actual"}
                port_value = type(item) is int or (
                    isinstance(item, dict) and set(item) <= {"direction", "width", "signed", "bits", "known"}
                    and all(type(n) in (int, bool) or n in ("input", "output") for n in item.values())
                )
                private = (name in _PRIVATE_KEYS or name.startswith(("rtlagent_", "fpgachina_"))
                           or name.endswith(("_path", "_paths", "_dir", "_root", "_url", "_token", "_key")))
                if private and not (signal and port_value):
                    continue
                context = parent if parent in ("expected", "pre_expected") and key.isdecimal() else name
                result[self._text(key)] = self._public(item, context)
            return result
        if type(value) is int and abs(value) > 2**53 - 1:
            # The browser's JSON parser cannot exactly represent wider RTL values.
            return str(value)
        if value is None or type(value) in (bool, int, float):
            return value
        raise TypeError("live details must contain public JSON values")

    def _write(self, event, data, ts=None):
        # All events are serialized in full before the single, line-delimited write.
        row = {"v": 1, "ts": time.time() if ts is None else ts, "type": event, **data}
        if self.stream is not None:
            try:
                self.stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                self.stream.flush()
            except OSError:
                self.close()

    def _decode_tool_texts(self, messages):
        from agent.llm.structured import strict_json

        # Tool arguments and results often contain JSON inside a string. Learn
        # its credential values before publishing an echo elsewhere in this call.
        texts = [m.get("content") for m in messages if m.get("role") == "tool"]
        for message in messages:
            calls = message.get("tool_calls")
            if isinstance(calls, list):
                texts.extend(call["function"].get("arguments") for call in calls
                             if isinstance(call, dict) and isinstance(call.get("function"), dict))
        decoded = {}
        for text in texts:
            if not isinstance(text, str) or text in decoded:
                continue
            try:
                value = strict_json(text)
            except (ValueError, RecursionError):
                continue
            if isinstance(value, (dict, list)):
                self._tool_secrets._collect(value)
                decoded[text] = value
        return decoded

    def _tool_text(self, value, decoded):
        """Keep wire formatting when the structured arguments or result are public."""
        parsed = decoded.get(value)
        if parsed is not None:
            clean = self._public(parsed)
            return value if clean == parsed else json.dumps(clean, ensure_ascii=False)
        return self._text(value, model=True)

    def _string_fields(self, source, *keys):
        return {key: self._text(source[key]) for key in keys if isinstance(source.get(key), str)}

    def _tool_calls(self, values, decoded):
        calls = []
        for item in values:
            if not isinstance(item, dict):
                continue
            call = self._string_fields(item, "id", "type")
            function = item.get("function")
            if isinstance(function, dict):
                public = self._string_fields(function, "name")
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    public["arguments"] = self._tool_text(arguments, decoded)
                elif isinstance(arguments, (dict, list)):
                    public["arguments"] = self._public(arguments)
                call["function"] = public
            calls.append(call)
        return calls

    def _message(self, item, decoded):
        data = self._string_fields(item, "role", "name", "tool_call_id")
        content = item.get("content")
        if isinstance(content, str):
            data["content"] = (self._tool_text(content, decoded) if item.get("role") == "tool"
                               else self._text(content, model=True))
        elif isinstance(content, list):
            # Publish text parts. Media URLs, data, and provider metadata stay private.
            data["content"] = []
            for part in content:
                if isinstance(part, dict):
                    public = self._string_fields(part, "type")
                    if part.get("type") == "text" and isinstance(part.get("text"), str):
                        public["text"] = self._text(part["text"], model=True)
                    data["content"].append(public)
        elif "content" in item and content is None:
            data["content"] = None
        if isinstance(item.get("tool_calls"), list):
            data["tool_calls"] = self._tool_calls(item["tool_calls"], decoded)
        return data

    @best_effort
    def call_context(self, request):
        # The HTTPX hook runs after serialization and admission, just before
        # transfer to the transport. Backend receipt is still unknown.
        call_id = request.extensions.get("live_call_id")
        if call_id is None or self.stream is None:
            return
        messages = json.loads(request.content).get("messages")
        data = {}
        if isinstance(messages, list):
            messages = [m if isinstance(m, dict) else {} for m in messages]
            decoded = self._decode_tool_texts(messages)
            data["messages"] = [self._message(m, decoded) for m in messages]
        data.update(id=self.current, call_id=self._text(call_id), purpose=self._text(request.extensions["purpose"]))
        self._write("call_context", data)

    @best_effort
    def call_response(self, call_id, purpose, choice):
        if self.stream is None:
            return
        # The client calls this only for the adopted choice. Preserve missing,
        # null and empty content, and the names of any native reasoning fields.
        message = choice["message"]
        decoded = self._decode_tool_texts([message])
        data = {"id": self.current, "call_id": self._text(call_id), "purpose": self._text(purpose)}
        data.update(self._public(fields(choice, "finish_reason")))
        if "content" in message:
            content = message["content"]
            data["content"] = self._text(content, model=True) if isinstance(content, str) else None
        for key in ("reasoning_content", "reasoning"):
            if isinstance(message.get(key), str):
                data[key] = self._text(message[key], model=True, native_reasoning=True)
        if isinstance(message.get("tool_calls"), list):
            data["tool_calls"] = self._tool_calls(message["tool_calls"], decoded)
        self._write("call_response", data)

    @best_effort
    def detail(self, label, value, *, kind=None, status=None):
        kind = kind or ("text" if isinstance(value, str) else "json")
        if kind not in ("code", "text", "json"):
            return
        if kind == "json" and not isinstance(value, (dict, list)):
            return
        if kind in ("code", "text") and not isinstance(value, str):
            return
        data = {
            "id": self.current, "label": self._text(label), "kind": kind,
            "value": self._text(value, code=True) if kind == "code" else self._public(value),
        }
        if isinstance(status, str):
            data["status"] = self._text(status)
        self._write("detail", data)

    @best_effort
    def event(self, row):
        tool, event = row["tool"], row["event"]
        if (tool, event) == ("run", "graph"):
            from agent.tools.registry import NODES

            self.nodes = {}
            for alias, definition in row["nodes"].items():
                impl = definition.get("use")
                label, role = self.rtl.node_titles.get(impl, (alias, None))
                registered = NODES.get(impl)
                if registered:
                    label = getattr(registered, "label", None) or label
                    role = getattr(registered, "role", None) or role
                node = {"id": self._text(alias), "label": self._text(label)}
                if role:
                    node["role"] = self._text(role)
                self.nodes[alias] = node
            self._write("graph", {
                "workflow": self._text(row["workflow"]), "entrypoint": self._text(row["entrypoint"]),
                "nodes": list(self.nodes.values()),
                "edges": [self._public(fields(edge, "from", "to", "condition")) for edge in row["transitions"]],
            }, row["ts"])
        elif tool == "node" and event == "started":
            self.visits += 1
            self.current = row.get("span_id") or f"step-{self.visits}"
            alias = row["name"]
            node = self.nodes.get(alias) or {"id": self._text(alias), "label": self._text(alias)}
            self._write("node_start", {
                **fields(node, "label", "role"), "node": node["id"], "id": self.current, "previous": self.previous,
            }, row["ts"])
            self.previous = self.current
        elif tool == "node" and event in ("finished", "failed") and self.current:
            self._write("node_end", {"id": self.current, "status": event, **fields(row, "elapsed_s")}, row["ts"])
            self.current = None
        elif (tool, event) == ("run", "failed"):
            self.detail("运行错误", fields(row, "error_type"), status="failed")
        elif (tool, event) == ("run", "end"):
            data = fields(row, "status", "submission_mode", "candidate_id", "stop_reason",
                          "elapsed_s", "calls", "tokens_in", "tokens_out")
            if row.get("status") == "error":
                # Exception messages can contain complete host settings or CLI arguments.
                category = str(row.get("stop_reason", "error")).split(":", 1)[0]
                data["stop_reason"] = category if category.isidentifier() else "error"
            if self.current and row.get("status") in ("error", "stopped"):
                self._write("node_end", {"id": self.current, "status": "failed"}, row["ts"])
                self.current = None
            self._write("run_end", self._public(data), row["ts"])
        elif tool in ("llm", "tool", "guided_observe") and event in ("started", "finished", "failed"):
            if tool == "llm":
                label = "模型调用"
                data = fields(row, "call_id", "purpose", "finish_reason", "error_kind", "empty_content",
                              "elapsed_s", "tokens_in", "tokens_out")
            else:
                label = "工具调用" if tool == "tool" else "仿真采样"
                data = fields(row, "name", "candidate_id", "elapsed_s", "error_type", "origin")
                if isinstance(row.get("input"), dict):
                    data.update(fields(row["input"], "candidate_id"))
            self.detail(label, data, status=event)
        elif event == "result" and isinstance(row.get("output"), dict) and row.get("status"):
            data = fields(row, "status", "rc", "failure_kind")
            if data["status"] == "passed" and (type(data.get("rc")) is not int or data["rc"] != 0):
                data["status"] = "unverified"
            self.detail("工具结果 · " + tool, data, status=data["status"])
        else:
            self.rtl.event(tool, event, row)

    @best_effort
    def artifact(self, relative, value):
        # Only named domain artifacts enter the projection; paths never leave it.
        name = str(relative)
        candidate = re.fullmatch(r"candidates/(c[0-9]+)\.v", name)
        if candidate and isinstance(value, str):
            self.detail("候选 RTL · " + candidate[1], value, kind="code")
        elif name.startswith("guided/") and name.endswith(".json") and not name.startswith("guided/history/"):
            self.rtl.artifact(name[len("guided/"):-len(".json")], value)

    @best_effort
    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            stream.close()
