"""Public call events at the HTTPX boundary, using self-authored transport fixtures."""

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json

import httpx
import pytest

from agent.llm.client import Client, ModelError
from agent.observability.recorder import Recorder
from agent.runtime.allowance import AllowanceError, CompletionLedger
from agent.runtime.budget import Budget


def rows(directory):
    return [json.loads(line) for line in (directory / "live.jsonl").read_text().splitlines()]


@contextmanager
def run_client(directory, transport, *, config=None, generation=None):
    with ExitStack() as cleanup:
        record = Recorder(directory, level="basic", secrets=["synthetic-known-credential"])
        cleanup.callback(record.close)
        client = Client({"model": "fixture", **(config or {})}, Budget(90, 1), record,
                        generation or {}, transport=httpx.MockTransport(transport))
        cleanup.callback(client.close)
        yield client, record


def test_capture_on_dispatch_and_adoption_uses_separate_allowlisted_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    args = ('{ "candidate_id": "c01", "headers": {"X-Debug": "private-header"},'
            ' "api_key": "private-encoded-key", "echo": "private-encoded-key" }')
    tool = {"id": "tc-3", "type": "function", "function": {"name": "check", "arguments": args,
            "vendor_info": "private-function"}, "provider_info": "private-tool"}
    note = "Public instructions\n" * 250
    messages = [
        {"role": "system", "content": note, "provider_info": "private-system"},
        {"role": "user", "name": "designer", "content": [
            {"type": "text", "text": "Compare token <= val, then assign q=a / b;\nEcho private-encoded-key"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,private-media"}},
        ]},
        {"role": "assistant", "content": None, "reasoning_content": "private-request-extension",
         "tool_calls": [tool]},
        {"role": "tool", "tool_call_id": "tc-3",
         "content": '{"ok": true, "stdout": "private-stdout", "host": "private-host"}'},
    ]
    rtl = ("module Test(input a, b, output reg token, output q); assign q=a /b;\n"
           "always @* begin token = a / b; end\n"
           'initial $display("api_key=unlisted-credential /host/secrets/log"); endmodule')
    message = {"content": rtl + "\n<think>inline-analysis</think>", "tool_calls": [tool],
               "reasoning": "Native A synthetic-known-credential or private-provider-credential",
               "reasoning_content": "<think>Native B</think> </private/machine>\nCookie: id=private-cookie; other=x",
               "analysis": "private-debug"}
    before = deepcopy((messages, message))

    def transport(request):
        assert json.loads(request.content)["messages"] == messages
        context = rows(tmp_path)[-1]
        assert context["type"] == "call_context" and context["id"] == visit_id
        assert context["messages"][0] == {"role": "system", "content": note}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "tool_calls"}],
                                         "provider_info": {"api_key": "private-provider-credential"}})

    with run_client(tmp_path, transport, generation={"messages": messages}) as (client, record):
        with record.span("node", name="design"):
            visit_id = rows(tmp_path)[0]["id"]
            # Without a ledger the existing generation configuration can override messages.
            reply = client.chat([{"role": "user", "content": "unused-preparation"}], purpose="design")
        assert reply.content == message["content"] and reply.tool_calls == [tool]
        assert reply.reasoning == {k: message[k] for k in ("reasoning_content", "reasoning")}
        assert (messages, message) == before
        assert client.usage_summary()["calls"] == 1

    events = rows(tmp_path)
    context, response = [r for r in events if r["type"] in ("call_context", "call_response")]
    for row in (context, response):
        assert (row["v"], row["id"], row["call_id"], row["purpose"]) == (1, visit_id, reply.call_id, "design")
    text, media = context["messages"][1]["content"]
    assert text == {"type": "text", "text": "Compare token <= val, then assign q=a / b;\nEcho [凭据已隐藏]"}
    assert media == {"type": "image_url"}
    saved_tool = context["messages"][2]["tool_calls"]
    assert context["messages"][2]["content"] is None and saved_tool == response["tool_calls"]
    assert json.loads(saved_tool[0]["function"]["arguments"]) == {"candidate_id": "c01", "echo": "[凭据已隐藏]"}
    assert json.loads(context["messages"][3]["content"]) == {"ok": True}
    assert context["messages"][3]["tool_call_id"] == saved_tool[0]["id"]
    assert "assign q=a /b;\nalways @* begin token = a / b; end" in response["content"]
    assert response["reasoning"].startswith("Native A ")
    assert response["reasoning_content"].startswith("<think>Native B</think>")
    assert response["finish_reason"] == "tool_calls"
    assert "Native A" not in response["content"] and "Native B" not in response["reasoning"]
    raw = (tmp_path / "live.jsonl").read_text()
    for hidden in ("synthetic-known-credential", "unlisted-credential", "/host/",
                   "private-", "inline-analysis", "unused-preparation"):
        assert hidden not in raw
    assert all("Native A" not in json.dumps(r) for r in events if r["type"] != "call_response")
    assert "Native B" not in (tmp_path / "trace.jsonl").read_text()


def test_no_completion_context_for_tokenizer_or_budget_denial(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    endpoints = []

    def transport(request):
        endpoints.append(request.url.path)
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "private-rendered-template"})
        assert request.url.path == "/tokenize"
        return httpx.Response(200, json={"tokens": [1, 2, 3]})

    config = {"max_model_len": 3, "tokenizer_protocol": "llama_cpp"}
    with run_client(tmp_path, transport, config=config) as (client, record):
        with pytest.raises(ModelError, match="exhausts model context"):
            client.chat([{"role": "user", "content": "private-preparation"}])
        client.config["max_model_len"] = None
        ledger = CompletionLedger(client.budget, record, 1, 12)
        permit = ledger.reserve("design", 12, 5)

        def deny(call_id, max_tokens):
            raise AllowanceError("permit expired during preparation")

        monkeypatch.setattr(permit, "_sent", deny)
        with client.permitted(permit), pytest.raises(ModelError, match="expired"):
            client.chat([{"role": "user", "content": "private-denied"}], max_tokens=12)
        assert ledger.snapshot()["calls_sent"] == client.usage_summary()["calls"] == 0
    assert endpoints == ["/apply-template", "/tokenize"]
    events = rows(tmp_path)
    assert not any(r["type"] in ("call_context", "call_response") for r in events)
    assert events[-1]["status"] == "failed" and events[-1]["value"]["error_kind"] == "allowance"
    assert "private-" not in (tmp_path / "live.jsonl").read_text()


@pytest.mark.parametrize("kind", ["connection", "http", "invalid_json", "response"])
def test_failed_dispatch_has_context_without_a_fabricated_reply(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")

    def transport(request):
        if kind == "connection":
            raise httpx.ConnectError("private-debug", request=request)
        if kind == "http":
            return httpx.Response(500, json={"error": "private-debug"})
        if kind == "invalid_json":
            return httpx.Response(200, text="private-debug")
        return httpx.Response(200, json={"choices": [{"message": {"content": ["private-debug"]}}]})

    with run_client(tmp_path, transport) as (client, _):
        with pytest.raises(ModelError) as error:
            client.chat([{"role": "user", "content": "hello"}])
        assert error.value.kind == kind
    events = rows(tmp_path)
    context, = [r for r in events if r["type"].startswith("call_")]
    assert context["type"] == "call_context" and context["id"] is None
    assert events[-1]["status"] == "failed" and events[-1]["value"]["error_kind"] == kind
    assert "private-debug" not in (tmp_path / "live.jsonl").read_text()


@pytest.mark.parametrize(("message", "finish"), [
    ({"content": None, "reasoning_content": "native fixture"}, "length"),
    ({"content": "", "reasoning": {"opaque": "private-provider"}}, "stop"),
    ({"role": "assistant"}, None),
])
def test_missing_null_and_empty_final_text_are_preserved(tmp_path, monkeypatch, message, finish):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    choice = {"message": message, "finish_reason": finish}
    with run_client(tmp_path, lambda req: httpx.Response(200, json={"choices": [choice]})) as (client, _):
        reply = client.chat([])
    response, = [r for r in rows(tmp_path) if r["type"] == "call_response"]
    assert ("content" in response) == ("content" in message)
    assert response.get("content") == message.get("content") and response["finish_reason"] == finish
    assert response.get("reasoning_content") == message.get("reasoning_content")
    assert "reasoning" not in response and "tool_calls" not in response and reply.content == ""


def test_tool_request_and_actual_feedback_share_the_backend_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    actual = []
    args = '{ "n" : 2, "expected": {"token": 1} }'
    tool = {"id": "from-backend", "type": "function",
            "function": {"name": "increment", "arguments": args}}
    replies = iter([{"content": None, "tool_calls": [tool]}, {"content": "done"}])

    def transport(request):
        actual.append(json.loads(request.content)["messages"])
        msg = next(replies)
        return httpx.Response(200, json={"choices": [{"message": msg,
                              "finish_reason": "tool_calls" if "tool_calls" in msg else "stop"}]})

    with run_client(tmp_path, transport) as (client, _):
        client.tool_dispatch = lambda name, params: {"n": params["n"] + 1}
        reply = client.run_tools([{"role": "user", "content": "Add one"}],
                                 tools=[{"type": "function", "function": {"name": "increment"}}])
        assert reply.content == "done"
    outgoing, tool_request, followup, final = [r for r in rows(tmp_path) if r["type"].startswith("call_")]
    assert [outgoing["messages"], followup["messages"]] == actual
    assert outgoing["call_id"] == tool_request["call_id"] != final["call_id"] == followup["call_id"]
    assert "tool_calls" not in final and tool_request["tool_calls"] == [tool]
    feedback = followup["messages"][-1]
    assert feedback == {"role": "tool", "tool_call_id": tool["id"], "content": '{"n": 3}'}


def test_failed_http_serialization_has_no_dispatch_event(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")

    def transport(request):
        pytest.fail("HTTPX cannot dispatch non-finite JSON")

    with run_client(tmp_path, transport) as (client, _):
        with pytest.raises(ValueError, match="JSON"):
            client.chat([{"role": "user", "content": "private-unsent"}], temperature=float("nan"))
    assert not any(r["type"].startswith("call_") for r in rows(tmp_path))
    assert "private-unsent" not in (tmp_path / "live.jsonl").read_text()


def test_disabled_live_view_keeps_the_existing_transport(tmp_path, monkeypatch):
    monkeypatch.delenv("RTLAGENT_LIVE_EVENTS", raising=False)

    def transport(request):
        assert "live_call_id" not in request.extensions
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    with run_client(tmp_path, transport) as (client, _):
        assert client.chat([]).content == "done"
    assert not (tmp_path / "live.jsonl").exists()
