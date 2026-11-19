"""Self-authored routing and immutable-evidence regressions; no model or EDA."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.guided_checker import parse_checker
from agent.domain.rtl.observation import TraceRun, sampling_hash
from agent.domain.rtl.result import CheckResult
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.observability.recorder import Recorder
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters


PROMPT = """Implement a module named TopModule with this interface.
 - input a
 - output y
The output y equals input a."""


class GuidedBugfixTests(unittest.TestCase):
    def context(self, *, level="full", max_calls=8):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        recorder = Recorder(directory.name, level=level)
        self.addCleanup(recorder.close)
        code = "module TopModule(input a, output y); assign y = a; endmodule\n"
        ctx = SimpleNamespace(
            task=TaskSpec.from_text("self-authored-evidence", PROMPT),
            store={}, record=recorder, prompts=TemplateRenderer(),
            budget=SimpleNamespace(remaining=lambda: 1000.0),
            candidates=CandidateStore(recorder, directory.name),
        )
        guided.initialize(ctx, State({"settings": GuidedParameters(max_calls=max_calls).model_dump()}))
        ctx.store["guided"].update(method="table", plan={"skills": [], "knowledge": []}, plan_source="planner")
        candidate = ctx.candidates.create(code, source_stage="self_authored")
        ctx.store["submission"].register(candidate, reason="initial sample")
        return ctx

    def structure(self, ctx, *, lint, synth=None, built=False):
        if built:
            table = "case probe # y follows an input of zero.\nstep a=0 y=0"
            guided._set_checker(ctx, parse_checker(table, ctx.task, require_explanations=True), table)
        calls = []

        def call(stage, **kwargs):
            calls.append(stage)
            if stage == "interface":
                return CheckResult("passed", "self-authored interface")
            if stage == "lint":
                return lint
            if stage == "synth":
                return synth or CheckResult("passed", "stub synthesis")
            self.fail(f"unexpected tool {stage}")

        ctx.call = call
        state = guided.structure(ctx, State({"target_id": "c001", "method": "table"}))
        return state["action"], calls

    def test_compile_failure_still_repairs_when_budget_remains(self):
        ctx = self.context()
        action, calls = self.structure(
            ctx, lint=CheckResult("failed", "syntax", failure_kind="code"),
        )
        self.assertEqual(action, "repair_structure")
        self.assertEqual(calls, ["interface", "lint"])

    def test_exhausted_compile_failure_neither_builds_nor_runs_checker(self):
        for built in (False, True):
            with self.subTest(existing_checker=built):
                ctx = self.context(max_calls=1)
                data = ctx.store["guided"]
                permit = data["ledger"].reserve("previous", max_tokens=1, timeout_s=1)
                permit._begin()
                permit._sent("m1", 1)
                permit._response({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})
                permit._finish()
                action, calls = self.structure(
                    ctx, lint=CheckResult("failed", "syntax", failure_kind="code"),
                    built=built,
                )
                self.assertEqual(action, "repair_structure")
                state = guided.repair_structure(ctx, State({"target_id": "c001"}))
                self.assertEqual(guided.structure(ctx, state)["action"], "finish")
                self.assertEqual(data["request_outcomes"]["repair_structure"]["reason"], "call_limit")
                self.assertEqual(calls, ["interface", "lint"])
                self.assertFalse(ctx.store["guided"]["assessments"]["c001"]["structural_passed"])

    def test_synthesis_code_failure_repairs_before_behavior_can_run(self):
        for built in (False, True):
            with self.subTest(existing_checker=built):
                ctx = self.context()
                action, calls = self.structure(
                    ctx, lint=CheckResult("passed", "compiled"),
                    synth=CheckResult("failed", "not synthesizable", failure_kind="code"),
                    built=built,
                )
                self.assertEqual(action, "repair_structure")
                self.assertEqual(calls, ["interface", "lint", "synth"])
                self.assertEqual(ctx.store["guided"]["assessments"]["c001"]["checks"]["lint"]["status"], "passed")

    def test_unknown_compile_outcome_is_not_treated_as_code_failure(self):
        for status, kind in (("timeout", "timeout"), ("unavailable", "environment"),
                             ("failed", "unknown"), ("error", "environment")):
            for built in (False, True):
                with self.subTest(status=status, kind=kind, existing_checker=built):
                    ctx = self.context()
                    action, _ = self.structure(
                        ctx, lint=CheckResult(status, "unconfirmed", failure_kind=kind),
                        built=built,
                    )
                    self.assertEqual(action, "author_decision")

    def test_conflicting_pass_status_and_return_code_leave_the_gate_unverified(self):
        for stage in ("lint", "synth"):
            with self.subTest(stage=stage):
                ctx = self.context()
                checks = {"lint": CheckResult("passed", "compiled", rc=0)}
                checks[stage] = CheckResult("passed", "contradictory tool exit", rc=1)
                action, calls = self.structure(ctx, **checks)
                self.assertEqual(action, "author_decision")
                self.assertFalse(ctx.store["guided"]["assessments"]["c001"]["toolchain_passed"])
                if stage == "lint":
                    self.assertNotIn("synth", calls)

    def artifacts(self, ctx, name):
        events = [json.loads(line) for line in
                  (ctx.record.output_dir / "trace.jsonl").read_text().splitlines()]
        return [event for event in events if event["tool"] == "guided"
                and event["event"] == "artifact" and event["name"] == name]

    def load_artifacts(self, ctx, name):
        events = self.artifacts(ctx, name)
        paths = [Path(event["path"]) for event in events]
        self.assertEqual(len(paths), len(set(paths)), "past events must not alias mutable files")
        return [json.loads(path.read_text()) for path in paths]

    def test_repeated_structure_events_retain_first_failure(self):
        ctx = self.context()
        self.structure(ctx, lint=CheckResult("failed", "first syntax failure", failure_kind="code"))
        self.structure(ctx, lint=CheckResult("passed", "later compile success"))
        evidence = self.load_artifacts(ctx, "assessments/c001/lint")
        self.assertEqual([item["status"] for item in evidence], ["failed", "passed"])
        self.assertIn("first syntax failure", evidence[0]["excerpt"])
        latest = json.loads((ctx.record.record_dir / "guided/assessments/c001/lint.json").read_text())
        self.assertEqual(latest, evidence[-1])
        assessments = self.load_artifacts(ctx, "assessments/c001/assessment")
        self.assertEqual([item["structural_passed"] for item in assessments], [False, True])

    def trace(self, checker, candidate, value, execution, *, input_value=0):
        # Explicit samples are authored independently of checker expected values.
        rows = [{"case_id": "probe", "case_index": 0, "step": 0,
                 "clock_tick": tick, "phase": phase, "sample": True, "edge": False,
                 "values": {"a": {"bits": input_value, "known": 1, "width": 1},
                            "y": {"bits": value, "known": 1, "width": 1}}}
                for phase, tick in (("pre", 0), ("post", 1))]
        return TraceRun("complete", sampling_hash(checker.plan), candidate.code_hash,
                        execution, rows, "self-authored stub observation")

    def test_behavior_events_and_checker_versions_remain_reconstructible(self):
        ctx = self.context()
        data = ctx.store["guided"]
        table = "case probe # y follows an input of zero.\nstep a=0 y=0"
        checker = parse_checker(table, ctx.task, require_explanations=True)
        guided._set_checker(ctx, checker, table)
        original_hash = data["checker_hash"]
        candidate = ctx.candidates.get("c001")
        for value, execution in ((1, "first-observation"), (0, "second-observation")):
            trace = self.trace(checker, candidate, value, execution)
            with patch.object(guided, "observe", return_value=trace):
                guided.run_checker(ctx, State({"target_id": "c001"}))
        new_table = "case probe # y follows an input of one.\nstep a=1 y=1"
        rebuilt = parse_checker(new_table, ctx.task, require_explanations=True)
        guided._set_checker(ctx, rebuilt, new_table)
        rebuilt_hash = data["checker_hash"]
        self.assertNotEqual(original_hash, rebuilt_hash)
        trace = self.trace(rebuilt, candidate, 1, "rebuilt-observation", input_value=1)
        with patch.object(guided, "observe", return_value=trace):
            guided.run_checker(ctx, State({"target_id": "c001"}))
        behaviors = self.load_artifacts(ctx, "assessments/c001/behavior")
        self.assertEqual([item["status"] for item in behaviors], ["failed", "passed", "passed"])
        self.assertEqual([item["checker_hash"] for item in behaviors],
                         [original_hash, original_hash, rebuilt_hash])
        self.assertTrue(all(item["compared_bits"] > 0 for item in behaviors))
        observations = self.load_artifacts(ctx, "assessments/c001/observations")
        self.assertEqual([item["execution_id"] for item in observations],
                         ["first-observation", "second-observation", "rebuilt-observation"])
        self.assertEqual(observations[-1]["plan_hash"], sampling_hash(rebuilt.plan))
        checkers = self.load_artifacts(ctx, "checker")
        self.assertEqual([entry["checker_hash"] for entry in checkers], [original_hash, rebuilt_hash])
        self.assertEqual([entry["cases"] for entry in checkers],
                         [checker.public_dict()["cases"], rebuilt.public_dict()["cases"]])
        latest = json.loads((ctx.record.record_dir / "guided/checker.json").read_text())
        self.assertEqual(latest, checkers[-1])
        latest_behavior = json.loads(
            (ctx.record.record_dir / "guided/assessments/c001/behavior.json").read_text())
        self.assertEqual(latest_behavior, behaviors[-1])
        self.assertEqual(latest_behavior["checker_hash"], rebuilt_hash)
        latest_observation = json.loads(
            (ctx.record.record_dir / "guided/assessments/c001/observations.json").read_text())
        self.assertEqual(latest_observation, observations[-1])

    def test_basic_recording_does_not_advertise_nonexistent_attachments(self):
        ctx = self.context(level="basic")
        guided._save(ctx, "checker", {"status": "first"})
        guided._save(ctx, "checker", {"status": "second"})
        events = self.artifacts(ctx, "checker")
        self.assertEqual([event["status"] for event in events], ["first", "second"])
        self.assertTrue(all(event.get("path") is None for event in events))
        self.assertFalse(ctx.record.record_dir.exists())


if __name__ == "__main__":
    unittest.main()
