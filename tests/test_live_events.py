"""Self-authored workflow, candidate and checker evidence; no network or EDA."""

import json
from unittest.mock import patch
import pytest

from agent.config import Config, load_config
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.observation import TraceRun, sampling_hash
from agent.domain.rtl.result import CheckResult
from agent.domain.rtl.task import TaskSpec
from agent.kit import Ctx, State, default, node, when, workflow
from agent.llm.client import Client
from agent.llm.mock import make_transport
from agent.observability.recorder import Recorder
from agent.orchestration.graph import build_graph, run_graph
from agent.orchestration.nodes import guided, checks
import agent.orchestration.workflows  # register the built-in workflows
from agent.runtime.budget import Budget
from agent.tools.registry import NODES, WORKFLOWS


PROMPT = """Implement a module named TopModule with the following interface.
 - input a
 - output token
The output token equals input a."""


def rows(record):
    return [json.loads(line) for line in (record.output_dir / "live.jsonl").read_text().splitlines()]


def context(config, record, llm=None):
    return Ctx(task=TaskSpec.from_text("self-authored-live", PROMPT),
               budget=llm.budget if llm else Budget(900, 1), llm=llm, record=record, processes=None,
               candidates=CandidateStore(record, record.output_dir), prompts=TemplateRenderer(), config=config)


def test_new_workflow_uses_real_graph_flushes_each_visit_and_filters_private_state(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    monkeypatch.setenv("RTLAGENT_UI_OPERATOR_TOKEN", "operator-test-secret")
    monkeypatch.setenv("FPGACHINA_TOKEN", "contest-test-secret")
    monkeypatch.setenv("RTLAGENT_UI_TASK_ROOTS", "/private/tasks/root")
    _, evidence = load_config()
    assert not any(key.startswith("RTLAGENT_UI_") or key == "RTLAGENT_LIVE_EVENTS"
                   for key in evidence["environment"])
    record = Recorder(tmp_path / "output", root=tmp_path / "external")
    try:
        with patch.dict(NODES), patch.dict(WORKFLOWS):
            @node("test_count", reads=["count"], writes=["count"], label="计数", role="计数员")
            def count(ctx: Ctx, state: State) -> State:
                value = state["count"] + 1
                ctx.record.live_detail("公开进度", {
                    "count": value, "path": "/private/progress", "authorization": "internal-auth",
                    "reasoning_content": "model-private-work", "config": {"server": "internal-host"},
                    "note": "operator-test-secret, contest-test-secret in /private/progress; check x.",
                })
                return state.update(count=value)

            @workflow("counter_demo", nodes={"again": "test_count", "last": "test_count"}, state={"count": 0})
            def demo(g, p):
                return g.with_transitions(("again", "again", when(count=1)), ("again", "last", default)).with_entrypoint("again")

            app = build_graph(context(Config(workflow="counter_demo"), record))
            graph, = rows(record)
            assert graph["entrypoint"] == "again" and graph["workflow"] == "counter_demo"
            assert graph["nodes"][0] == {"id": "again", "label": "计数", "role": "计数员"}
            assert [(e["from"], e["to"]) for e in graph["edges"]] == [("again", "again"), ("again", "last")]
            for i in range(3):
                app.step()
                assert rows(record)[-1]["type"] == "node_end"
                assert sum(r["type"] == "detail" for r in rows(record)) == i + 1
        record.live_detail("额外信息", "ignored by the competition trace")
        record.emit("run", "end", status="completed", elapsed_s=1.0, calls=0, tokens_out=None)
        events = rows(record)
        starts = [r for r in events if r["type"] == "node_start"]
        assert [r["node"] for r in starts] == ["again", "again", "last"]
        ids = [r["id"] for r in starts]
        assert len(set(ids)) == 3 and [r["previous"] for r in starts] == [None, *ids[:2]]
        assert [r["id"] for r in events if r["type"] == "node_end"] == ids
        assert [r["id"] for r in events if r.get("label") == "公开进度"] == ids
        assert events[-2]["id"] is None
        assert events[-1]["type"] == "run_end" and events[-1]["tokens_out"] is None
        assert all(r["v"] == 1 and isinstance(r["ts"], float) for r in events)
        text = (record.output_dir / "live.jsonl").read_text()
        for private in ("/private", "internal-auth", "internal-host", "model-private-work",
                        "operator-test-secret", "contest-test-secret", "FPGACHINA_TOKEN", str(tmp_path)):
            assert private not in text
        assert record.record_dir.parent == tmp_path / "external"
        assert not list(record.record_dir.rglob("live.jsonl"))
        assert "ignored by the competition trace" not in (record.output_dir / "trace.jsonl").read_text()
    finally:
        record.close()


def test_opt_in_only_and_optional_failures_do_not_break_recording(tmp_path, monkeypatch):
    for i, flag in enumerate((None, "", "0", "true", "yes")):
        monkeypatch.delenv("RTLAGENT_LIVE_EVENTS", raising=False)
        if flag is not None:
            monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", flag)
        record = Recorder(tmp_path / str(i), level="basic")
        record.live_detail("off", {"work": 1})
        record.close()
        assert not (record.output_dir / "live.jsonl").exists()
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    bad = tmp_path / "cannot-create"
    (bad / "live.jsonl").mkdir(parents=True)
    for directory in (bad, tmp_path / "normal"):
        record = Recorder(directory, level="basic")
        try:
            record.live_detail("unserializable", {"x": object()})
            record.emit("run", "end", status="error",
                        stop_reason="ValueError: configuration contains host-details")
            assert json.loads((directory / "trace.jsonl").read_text())["status"] == "error"
            if directory != bad:
                row, = rows(record)
                assert row["stop_reason"] == "ValueError"
        finally:
            record.close()


def test_single_generate_uses_same_stream_and_node_failures_retain_their_status(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    config = Config(workflow="single_generate", services={"model": {"backend": "mock"}})
    record = Recorder(tmp_path / "single", level="basic")
    llm = Client(config.services.model, Budget(900, 1), record, {}, transport=make_transport())
    try:
        ctx = context(config, record, llm)
        state = run_graph(ctx)
        assert state["status"] == "completed"
        events = rows(record)
        assert [r["node"] for r in events if r["type"] == "node_start"] == ["generate", "extract", "select", "finish"]
        rtl, = [r for r in events if r.get("kind") == "code"]
        assert rtl["value"] == (record.output_dir / "solution.v").read_text()
        assert any(r.get("label") == "已选候选" and r["value"]["candidate_id"] == "c001" for r in events)
    finally:
        llm.close()
        record.close()

    record = Recorder(tmp_path / "failure", level="basic")
    try:
        with patch.dict(NODES), patch.dict(WORKFLOWS):
            @node("test_live_error")
            def fail(ctx: Ctx, state: State) -> State:
                raise RuntimeError("host-only exception detail")

            @workflow("fails_once", nodes={"first": "test_live_error"})
            def failing_workflow(g, p):
                return g.with_entrypoint("first")

            with pytest.raises(RuntimeError, match="host-only"):
                run_graph(context(Config(workflow="fails_once"), record))
        start, end = rows(record)[-2:]
        assert (start["type"], end["type"], end["status"]) == ("node_start", "node_end", "failed")
        assert start["id"] == end["id"]
        assert "host-only exception detail" not in (record.output_dir / "live.jsonl").read_text()
    finally:
        record.close()


def test_unexecuted_checks_zero_comparisons_and_host_text_are_not_reported_as_success(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    monkeypatch.setenv("FPGACHINA_TOKEN", "contest-test-secret")
    record = Recorder(tmp_path, level="basic")
    try:
        record.emit("run", "config", configuration={"service": "model-config-secret", "path": "/host/private"})
        record.write_json("calls/m0001/request.json", {"messages": [{"content": "private-model-request"}]})
        record.write_json("calls/m0001/response.json", {"reasoning": "private-model-reasoning"})
        record.write_text("candidates/c001.v",
                          'module token; wire password; assign password = a/b; '
                          '$display("/host/private/TB.sv"); endmodule // FPGACHINA_TOKEN=contest-test-secret\n')
        record.write_json("guided/assessments/c001/assessment.json",
                          {"candidate_id": "c001", "checks": {"interface": {}}, "toolchain_passed": False})
        record.write_json("guided/assessments/c001/behavior.json", {
            "candidate_id": "c001", "status": "passed", "compared_bits": 0,
            "case_results": [{"case_id": "x", "status": "passed", "compared_bits": 0}],
            "summary": "observation stage 0 failed: host-only-process-output\nCookie: a=1; b=2",
        })
        draft, structure, behavior, point = rows(record)
        assert 'module token; wire password; assign password = a/b; $display("' in draft["value"]
        assert structure["value"]["not_run"] == ["lint", "synth"] and not structure["value"]["toolchain_passed"]
        assert behavior["status"] == point["status"] == "unknown"
        assert behavior["value"]["compared_bits"] == 0 and "comparisons" not in point["value"]
        raw = (record.output_dir / "live.jsonl").read_text()
        for secret in ("contest-test-secret", "FPGACHINA_TOKEN", "/host", "host-only-process-output", "b=2",
                       "model-config-secret", "private-model-request", "private-model-reasoning"):
            assert secret not in raw
        record.write_json("guided/checker.json", {"status": "valid", "checker_hash": "table-A", "cases": [
            {"id": "probe", "explanation": "Public criterion", "expected": {"0": {"y": 1}}}]})
        binding = {"candidate_id": "c001", "candidate_hash": "rtl-A", "checker_hash": "table-A",
                   "checker_version": "host-version", "sampling_plan_hash": "plan-A", "execution_id": "round-B"}
        record.write_json("guided/assessments/c001/behavior.json", {
            **binding, "status": "unavailable", "case_results": [], "compared_bits": 0})
        case = rows(record)[-1]
        assert case["value"]["case_id"] == "probe" and case["status"] == "not_run"
        record.write_json("guided/assessments/c001/observations.json", {
            "status": "complete", "candidate_hash": "rtl-A", "plan_hash": "plan-A", "execution_id": "older-round",
            "rows": [{"case_id": "probe", "step": 0, "phase": "post", "values": {"y": {"bits": 1}}}]})
        record.write_json("guided/assessments/c001/behavior.json", {
            **binding, "status": "passed", "compared_bits": 1,
            "case_results": [{"case_id": "probe", "status": "passed", "compared_bits": 1}]})
        summary, case = rows(record)[-2:]
        assert summary["status"] == case["status"] == "unverified"
        assert "comparisons" not in case["value"]
        record.emit("guided", "verification", **binding, behavior_status="passed", functional_passed=True)
        final = rows(record)[-1]["value"]
        assert final["behavior_status"] == "unverified" and final["functional_passed"] is None
        mask = 2**256 - 1
        record.live_detail("宽信号", {"expected": {"token": mask}, "actual": {"token": {"bits": mask, "known": mask}}})
        wide = rows(record)[-1]["value"]
        assert wide["expected"]["token"] == wide["actual"]["token"]["known"] == str(mask)
    finally:
        record.close()


def test_guided_basic_projects_full_drafts_real_point_verdicts_and_author_review(tmp_path, monkeypatch):
    monkeypatch.setenv("RTLAGENT_LIVE_EVENTS", "1")
    config = Config(params={"max_calls": 9, "max_output_tokens": None, "first_tools_s": 2},
                    services={"model": {"backend": "mock", "model": "mock"}})
    record = Recorder(tmp_path / "output", level="basic", root=tmp_path / "unused-record-root")
    first = ("module TopModule(input a, output token);\nwire secret;\nassign secret = a / 1;\n"
             + "// Ordinary public RTL comment\n" * 90 + "assign token = 1'b1;\nendmodule")
    revised = first.replace("token = 1'b1", "token = secret")
    plan = "method=table\nskills=rtl-sequential-state-update\nknowledge=\nfocus=low|high\nreason=Compare both levels."
    table = "case low # A low input gives zero.\nstep a=0 token=0\ncase high # A high input gives one.\nstep a=1 token=1"
    scripts = {
        "guided_plan": [plan], "guided_solve": [first], "guided_checker": [table],
        "guided_author_decision": ["action=review\ncase_id=low\nreason=Please confirm the low case."],
        "guided_checker_review": ["review low keep # The task explicitly requires zero for low."],
        "guided_author_decision_2": ["action=revise\nreason=Replace the constant with the input.\n```verilog\n"
                                    + revised + "\n```"],
        "guided_author_decision_3": ["action=submit\nreason=The corrected candidate passed both points."],
    }
    replies = {purpose: [{
        "model": "mock", "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        "choices": [{"message": {"role": "assistant", "content": content,
                                "reasoning_content": "private-model-thought"}, "finish_reason": "stop"}],
    } for content in values] for purpose, values in scripts.items()}
    llm = Client(config.services.model, Budget(900, 1), record, {}, transport=make_transport(responses=replies))
    try:
        ctx = context(config, record, llm)

        def test_observe(ctx, candidate, plan, *, timeout_s):
            samples = []
            # Simulated DUT outputs are independent of the expected checker values.
            for index, a in enumerate((0, 1)):
                for phase, tick in (("pre", 0), ("post", 1)):
                    output = 1 if candidate.id == "c001" else a
                    samples.append({"case_index": index, "case_id": ("low", "high")[index], "step": 0,
                                    "clock_tick": tick, "phase": phase, "sample": True, "edge": False,
                                    "values": {"a": {"width": 1, "known": 1, "bits": a},
                                               "token": {"width": 1, "known": 1, "bits": output}}})
            return TraceRun("complete", sampling_hash(plan), candidate.code_hash, "fixture-" + candidate.id, samples)

        check = CheckResult("passed", "Synthetic tool", details={
            "repair_diagnostics": {"items": [{"message": "Signal token in /private/files/test.sv:13"}]},
            "source_binding": {"paths": ["/private/files/test.sv"]}, "internal_only": "private-tool-value",
        })
        with patch.object(checks, "run_lint", return_value=check), patch.object(checks, "run_synth", return_value=check), \
             patch.object(guided, "observe", side_effect=test_observe):
            state = run_graph(ctx)
        assert state["status"] == "completed" and state["target_id"] == "c002"
        events = rows(record)
        by_label = {}
        for r in events:
            if r["type"] == "detail":
                by_label.setdefault(r["label"], []).append(r)
        for candidate_id in ("c001", "c002"):
            draft, = by_label["候选 RTL · " + candidate_id]
            assert draft["kind"] == "code" and draft["value"] == ctx.candidates.get(candidate_id).code
            assert len(draft["value"]) > 2000
        assert by_label["验证策略与所选技能"][0]["value"]["skills"] == ["rtl-sequential-state-update"]
        assert by_label["独立检查表"][0]["value"]["ports"]["token"]["width"] == 1
        assert by_label["检查表版本"][0]["value"]["checker_version"] == by_label["行为比对汇总"][0]["value"]["checker_version"]
        assert by_label["测试点 · low"][0]["value"]["expected"] == {"0": {"token": 0}}
        low = by_label["测试点比对 · low"]
        assert [r["status"] for r in low] == ["failed", "passed"]
        visits = [r["id"] for r in events if r["type"] == "node_start" and r["node"] == "run_checker"]
        assert [r["id"] for r in low] == visits and len(set(visits)) == 2
        for i, r in enumerate(low):
            point = r["value"]
            assert point["candidate_id"] == ("c001", "c002")[i]
            assert point["compared_bits"] == 1 and point["explanation"] == "A low input gives zero."
            assert point["checker_version"] and point["checker_hash"] and point["sampling_plan_hash"]
            sample, = point["comparisons"]
            assert sample["expected"] == {"token": 0} and sample["actual"]["token"]["bits"] == (1, 0)[i]
        assert by_label["检查员复核决定"][0]["value"]["review_reason"] == "The task explicitly requires zero for low."
        assert [r["value"]["action"] for r in by_label["作者决定"]] == ["generate", "review", "revise", "submit"]
        assert by_label["最终交付"][0]["value"]["target_id"] == "c002"
        assert by_label["结构检查汇总"][0]["value"]["not_run"] == []
        assert by_label["接口检查 · c001"] and by_label["编译与展开 · c001"] and by_label["综合 · c001"]
        assert {r["status"] for r in by_label["模型调用"]} == {"started", "finished"}
        assert {r["status"] for r in by_label["工具调用"]} == {"started", "finished"}
        raw = (record.output_dir / "live.jsonl").read_text()
        assert "/private" not in raw and "private-tool-value" not in raw
        responses = [r for r in events if r["type"] == "call_response"]
        assert [r["purpose"] for r in responses] == list(scripts)
        assert all(r["reasoning_content"] == "private-model-thought" for r in responses)
        assert all("private-model-thought" not in json.dumps(r)
                   for r in events if r["type"] != "call_response")
        assert not record.record_dir.exists()
    finally:
        llm.close()
        record.close()
