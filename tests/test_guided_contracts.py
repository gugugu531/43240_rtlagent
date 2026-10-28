"""guided_verify flat plan, checker table, and adjudication contracts."""

import unittest

from agent.domain.rtl.guided_adjudicate import AdjudicationError, parse_adjudication
from agent.domain.rtl.guided_checker import (
    CheckerError,
    evaluate_checker,
    parse_checker,
)
from agent.domain.rtl.guided_plan import PlanError, parse_plan
from agent.domain.rtl.observation import TraceRun, sampling_hash
from agent.domain.rtl.task import TaskSpec


PROMPT = """Implement a module named TopModule with the following interface.
 - input clk
 - input reset
 - input load
 - input data (8 bits)
 - output q (8 bits)
On each positive clock edge, reset sets q to 1; load sets q to data;
otherwise q keeps its value."""


def task():
    return TaskSpec.from_text("guided", PROMPT)


def rows_for(checker):
    plan = checker.plan
    rows = []
    for ci, case in enumerate(plan["cases"]):
        tick = 0
        for si, step in enumerate(case["steps"]):
            for phase in ("pre", "post"):
                if phase == "post":
                    tick += 1
                values = {}
                for name, port in plan["ports"].items():
                    width = port["width"]
                    full = (1 << width) - 1
                    if port["direction"] == "input":
                        if name == plan["clock"]["port"]:
                            number = 1 if phase == "post" else 0
                        else:
                            number = step["inputs"][name] & full
                        values[name] = {"bits": number, "known": full, "width": width}
                    else:
                        expected = checker.cases[ci].expected.get(si, {}).get(name, 0)
                        values[name] = {"bits": expected, "known": full, "width": width}
                rows.append({
                    "case_id": case["id"], "case_index": ci, "step": si,
                    "clock_tick": tick, "phase": phase, "sample": True,
                    "edge": step["edge"], "values": values,
                })
    return rows


class GuidedContractTests(unittest.TestCase):
    def test_plan_is_flat_and_ids_are_checked(self):
        plan = parse_plan(
            "method=table\nskills=rtl-sequential-state-update\n"
            "knowledge=card-a\nfocus=reset|load\nreason=sequential",
            skill_ids=["rtl-sequential-state-update"],
            card_ids=["card-a"],
        )
        self.assertEqual(plan.method, "table")
        self.assertEqual(plan.skills, ("rtl-sequential-state-update",))
        self.assertEqual(plan.focus, ("reset", "load"))
        filtered = parse_plan(
            "method=table\nskills=other\nknowledge=missing",
            skill_ids=[], card_ids=[],
        )
        self.assertEqual(filtered.skills, ())
        self.assertEqual(filtered.knowledge, ())
        with self.assertRaises(PlanError):
            parse_plan("{\"method\":\"table\"}", skill_ids=[], card_ids=[])

    def test_checker_requires_init_and_all_non_clock_inputs(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n"
            "step reset=0 load=1 data=a5 q=a5\n",
            task(), init_cycles=2,
        )
        self.assertEqual(checker.cases[0].init_count, 2)
        self.assertIn(1, checker.cases[0].expected)  # after final init edge
        self.assertIn(2, checker.cases[0].expected)
        with self.assertRaises(CheckerError):
            parse_checker("case reset\nstep reset=0 load=0 data=00 q=01\n", task())
        with self.assertRaises(CheckerError):
            parse_checker("case c\ninit reset=1 load=0 q=01\n", task())
        with self.assertRaises(CheckerError):
            parse_checker(
                "case c\ninit reset=1 load=0 data=00 q=01\n"
                "step reset=0 load=0 data=00 q=01 z=02\n",
                TaskSpec.from_text(
                    "x", "module TopModule(input clk, input reset, output q, output z); endmodule"
                ),
            )

    def test_checker_evaluation_passes_and_reports_partial_outputs(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n"
            "step reset=0 load=1 data=a5 q=a5\n",
            task(),
        )
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "a" * 64, "exec",
            rows_for(checker), "ok",
        )
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["unchecked_outputs"], [])

        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n",
            TaskSpec.from_text(
                "x",
                "Implement a module named TopModule with the following interface.\n"
                " - input clk\n - input reset\n - input load\n"
                " - input data (8 bits)\n - output q (8 bits)\n - output z\n"
                "Reset sets q to 1; load sets q to data; otherwise hold.",
            ),
        )
        # z is public but not checked; host must report partial, not full pass.
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "b" * 64, "exec2",
            rows_for(checker), "ok",
        )
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "partial_passed")
        self.assertEqual(result["unchecked_outputs"], ["z"])

    def test_mismatch_is_failed(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=02\n", task(), init_cycles=1
        )
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "c" * 64, "exec3",
            rows_for(checker), "ok",
        )
        # Force one actual value to differ from the expected 0x02.
        trace.rows[1]["values"]["q"]["bits"] = 1
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed"][0]["signal"], "q")

    def test_adjudication_is_flat_and_bounded(self):
        value = parse_adjudication(
            "decision=solution_error\nreason=reset mismatch\nfailed_cases=reset",
            case_ids=["reset"],
        )
        self.assertEqual(value.decision, "solution_error")
        with self.assertRaises(AdjudicationError):
            parse_adjudication("decision=maybe\nreason=x", case_ids=[])


if __name__ == "__main__":
    unittest.main()
