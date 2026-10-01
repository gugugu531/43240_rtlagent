from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.artifacts import ArtifactStore  # noqa: E402
from agent.llm import LLMResult, LLMTimeoutError  # noqa: E402
from agent.main import Trace, solve_agent  # noqa: E402
from agent.tools import ToolResult  # noqa: E402


def reply(code: str) -> LLMResult:
    return LLMResult(
        text=f"```verilog\n{code}```\n",
        finish_reason="stop",
        model="fake-model",
    )


class FakeLLM:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)

    def chat(self, messages):
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeToolchain:
    available = True
    reason = ""

    def __init__(self, lint_results, synth_results=()):
        self.lint_results = iter(lint_results)
        self.synth_results = iter(synth_results)

    def lint(self, source, top, timeout_s):
        return next(self.lint_results)

    def synth(self, source, top, timeout_s):
        return next(self.synth_results)


def tool_result(tool: str, status: str, summary: str) -> ToolResult:
    rc = {"ok": 0, "failed": 1, "timeout": 124, "unavailable": -1}[status]
    return ToolResult(tool, ((tool,),), rc, status, 0.01, summary)


class CandidateFlowTests(unittest.TestCase):
    def test_incomplete_extraction_is_explicitly_traced(self):
        llm = FakeLLM([
            LLMResult(
                text="```verilog\nmodule TopModule(input a, output q);\n```",
                finish_reason="length",
                model="fake-model",
            )
        ])
        tools = FakeToolchain(lint_results=[])

        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp, save_candidates=True)
            trace_path = Path(temp, "trace.jsonl")
            trace = Trace(str(trace_path))
            with patch("agent.main.RtlToolchain", return_value=tools), \
                    patch("agent.main.load_skills", return_value=[]), \
                    patch("agent.main.MAX_ROUNDS", 1):
                selected = solve_agent(
                    llm, trace, store, "Implement TopModule.", "", "TopModule"
                )
            trace.close()
            events = [
                json.loads(line) for line in trace_path.read_text().splitlines()
            ]

        extracted = [event for event in events if event.get("tool") == "extract"]
        self.assertIsNone(selected)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["status"], "incomplete")
        self.assertFalse(extracted[0]["complete"])
        self.assertTrue(extracted[0]["suspected_truncation"])
        self.assertTrue(extracted[0]["diagnostics"])

    def test_second_model_failure_preserves_first_candidate(self):
        first_code = "module TopModule; endmodule\n"
        llm = FakeLLM([
            reply(first_code),
            LLMTimeoutError("request timed out"),
        ])
        tools = FakeToolchain(
            lint_results=[tool_result("lint", "failed", "lint failed")]
        )

        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp, save_candidates=True)
            trace = Trace(str(Path(temp, "trace.jsonl")))
            with patch("agent.main.RtlToolchain", return_value=tools), \
                    patch("agent.main.load_skills", return_value=[]):
                selected = solve_agent(
                    llm, trace, store, "Implement TopModule.", "", "TopModule"
                )
            trace.close()

            self.assertIsNotNone(selected)
            self.assertEqual(selected.id, "c001")
            self.assertEqual(Path(temp, "solution.v").read_text(), first_code)
            self.assertEqual(Path(temp, "candidates", "c001.v").read_text(), first_code)

    def test_candidate_history_reconstructs_repairs_and_final_selection(self):
        first_code = "module TopModule; endmodule\n"
        second_code = "module TopModule; wire fixed; endmodule\n"
        llm = FakeLLM([reply(first_code), reply(second_code)])
        tools = FakeToolchain(
            lint_results=[
                tool_result("lint", "failed", "lint failed"),
                tool_result("lint", "ok", "lint ok"),
            ],
            synth_results=[
                tool_result("synth", "ok", "Synthesis finished")
            ],
        )

        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp, save_candidates=True)
            trace_path = Path(temp, "trace.jsonl")
            trace = Trace(str(trace_path))
            with patch("agent.main.RtlToolchain", return_value=tools), \
                    patch("agent.main.load_skills", return_value=[]):
                selected = solve_agent(
                    llm, trace, store, "Implement TopModule.", "", "TopModule"
                )
            trace.close()

            first = json.loads(Path(temp, "candidates", "c001.json").read_text())
            second = json.loads(Path(temp, "candidates", "c002.json").read_text())
            selection = json.loads(Path(temp, "selection.json").read_text())
            events = [
                json.loads(line) for line in trace_path.read_text().splitlines()
            ]

            self.assertEqual(first["source_stage"], "generate")
            self.assertEqual(first["extraction_status"], "ok")
            self.assertIsNone(first["parent_id"])
            self.assertEqual(second["source_stage"], "repair")
            self.assertEqual(second["parent_id"], "c001")
            self.assertEqual(selected.id, "c002")
            self.assertEqual(selection["candidate_id"], "c002")
            self.assertEqual(selection["reason"], "synth_passed")
            self.assertEqual(Path(temp, "solution.v").read_text(), second_code)
            created = [
                event for event in events
                if event.get("tool") == "candidate"
                and event.get("event") == "create"
            ]
            self.assertEqual(
                [event["candidate_id"] for event in created],
                ["c001", "c002"],
            )
            self.assertTrue(all(event.get("code_hash") for event in created))
            checked = [
                event for event in events
                if event.get("tool") in ("lint", "synth")
            ]
            self.assertEqual(
                [(event["tool"], event["status"]) for event in checked],
                [("lint", "failed"), ("lint", "ok"), ("synth", "ok")],
            )
            self.assertEqual(
                [event["candidate_id"] for event in checked],
                ["c001", "c002", "c002"],
            )
            self.assertTrue(all(event.get("command") for event in checked))


if __name__ == "__main__":
    unittest.main()
