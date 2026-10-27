"""Real-simulation acceptance for checker discrimination (Vivado-guarded, default skip).

Each test stages a correct RTL implementation and a wrong-RTL mutant with the same
behavior suite. testbench.simulate compiles and runs them with xvlog/xelab/xsim, so
a pass here proves the checker runs on real sampled values, and the failing mutant
proves it detects the specified case/step/signal/bit. The synthetic-trace counterpart
that always runs offline lives in tests/test_checker_discrimination.py.

Run manually when Vivado is installed (this round deliberately does not run Vivado):

    RTLA_CHECKER_SIM=1 python -m unittest tests.test_checker_sim_acceptance -v

The skip guard keeps a machine without xvlog from claiming simulator coverage; a
skipped test is not evidence that the RTL pair was compiled or simulated.
"""

import os
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from agent.config import ROOT, load_config
from agent.runtime.budget import Budget
from agent.runtime.process import ProcessManager
from agent.runtime.recorder import Recorder
from agent.rtl.candidate import CandidateFactory
from agent.rtl.suite.schema import validate_suite
from agent.rtl.suite.testbench import simulate
from agent.rtl.task import TaskSpec

SIM_READY = bool(shutil.which("xvlog")) and os.environ.get("RTLA_CHECKER_SIM") == "1"
SIM_GUARD = (
    "real simulation acceptance requires xvlog on PATH and RTLA_CHECKER_SIM=1; "
    "a skipped run is not simulator coverage"
)


def model_suite(ports, cases, requirements, *, clock, state, outputs):
    return validate_suite({
        "schema_version": 1, "mode": "behavior", "ports": ports, "clock": clock,
        "state": state, "outputs": outputs, "requirements": requirements, "cases": cases,
    })


def shift_direction_suite(task):
    # Synchronous reset clears q first, then the sampled path distinguishes which end
    # receives the new bit. The wrong RTL uses the same reset but shifts the other way.
    ports = {"clk": {"direction": "input", "width": 1},
             "reset": {"direction": "input", "width": 1},
             "d": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "shift_in_path", "requirements": ["R1"], "steps": [
        {"inputs": {"reset": 1, "d": 0}, "sample": True, "edge": True},
        {"inputs": {"reset": 0, "d": 1}, "sample": True, "edge": True},
        {"inputs": {"reset": 0, "d": 1}, "sample": True, "edge": True},
        {"inputs": {"reset": 0, "d": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [{"id": "R1", "quote": "d shifts into the low end of q"}]
    state = {"model_q": {"width": 4, "next": {"op": "ite", "width": 4, "args": [
        {"ref": "reset"}, {"const": 0, "width": 4},
        {"op": "concat", "width": 4, "args": [
            {"op": "slice", "width": 3, "lsb": 0, "args": [{"ref": "model_q"}]},
            {"ref": "d"}]}]}}}
    return model_suite(ports, cases, requirements,
                       clock={"port": "clk", "edge": "posedge"},
                       state=state, outputs={"q": {"ref": "model_q"}})


def sync_reset_suite(task):
    # The only observation that separates a synchronous reset from an asynchronous one
    # is the off-edge assertion step after q has moved away from zero.
    ports = {"clk": {"direction": "input", "width": 1},
             "reset": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "reset_off_edge_must_hold", "requirements": ["R1", "R2"], "steps": [
        {"inputs": {"reset": 1}, "sample": True, "edge": True},
        {"inputs": {"reset": 0}, "sample": True, "edge": True},
        {"inputs": {"reset": 1}, "sample": True, "edge": False},
        {"inputs": {"reset": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [
        {"id": "R1", "quote": "the synchronous reset clears q only at a rising clock edge"},
        {"id": "R2", "quote": "q holds when reset rises without a clock edge"},
    ]
    state = {"model_q": {"width": 4, "next": {"op": "ite", "width": 4, "args": [
        {"ref": "reset"}, {"const": 0, "width": 4},
        {"op": "add", "width": 4, "args": [{"ref": "model_q"}, {"const": 1, "width": 4}]}]}}}
    return model_suite(ports, cases, requirements,
                       clock={"port": "clk", "edge": "posedge"},
                       state=state, outputs={"q": {"ref": "model_q"}})


def unrelated_output_suite(task):
    # Both outputs get a sampled expectation; changing only o2 must still be caught.
    ports = {"a": {"direction": "input", "width": 1},
             "b": {"direction": "input", "width": 1},
             "c": {"direction": "input", "width": 1},
             "d": {"direction": "input", "width": 1},
             "o1": {"direction": "output", "width": 1},
             "o2": {"direction": "output", "width": 1}}
    cases = [
        {"id": "o1_case", "requirements": ["R1"], "steps": [
            {"inputs": {"a": 1, "b": 1, "c": 0, "d": 1}, "sample": True, "edge": False},
            {"inputs": {"a": 0, "b": 1, "c": 1, "d": 0}, "sample": True, "edge": False}]},
        {"id": "o2_case", "requirements": ["R2"], "steps": [
            {"inputs": {"a": 1, "b": 0, "c": 1, "d": 0}, "sample": True, "edge": False},
            {"inputs": {"a": 0, "b": 1, "c": 0, "d": 1}, "sample": True, "edge": False}]},
    ]
    requirements = [{"id": "R1", "quote": "o1 is a AND b"},
                    {"id": "R2", "quote": "o2 is c XOR d"}]
    outputs = {"o1": {"op": "and", "width": 1, "args": [{"ref": "a"}, {"ref": "b"}]},
               "o2": {"op": "xor", "width": 1, "args": [{"ref": "c"}, {"ref": "d"}]}}
    return model_suite(ports, cases, requirements, clock=None, state={}, outputs=outputs)


@unittest.skipUnless(SIM_READY, SIM_GUARD)
class CheckerSimAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Loading a shipped config is a cheap availability preflight; the test task
        # below is independent and no model transport is constructed.
        load_config(ROOT / "config/design_verify_loop.yaml", {})
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.record = Recorder(self.directory.name)
        self.addCleanup(self.record.close)

    def task(self, prompt, top="TopModule"):
        return TaskSpec.from_text("sim-acceptance", prompt, top=top)

    def run_rtl(self, rtl, suite, task):
        record = Recorder(tempfile.mkdtemp(dir=self.directory.name))
        self.addCleanup(record.close)
        budget = Budget(300.0, 5.0, record=record)
        processes = ProcessManager(budget, record)
        ctx = SimpleNamespace(task=task, record=record, budget=budget, processes=processes)
        candidate = CandidateFactory().create(rtl, source_stage="sim_acceptance", round=1)
        return simulate(ctx, candidate, suite, timeout_s=120.0)

    def assert_pair(self, task, suite, correct_rtl, wrong_rtl, *,
                    case_id, step, signal, expected_bits, actual_bits):
        passed = self.run_rtl(correct_rtl, suite, task)
        self.assertEqual(passed.status, "passed", passed.summary)
        self.assertEqual(passed.details["failed_cases"], [])
        self.assertGreater(passed.details["compared_bits"], 0)

        failed = self.run_rtl(wrong_rtl, suite, task)
        self.assertEqual(failed.status, "failed", failed.summary)
        self.assertIn(case_id, failed.details["failed_cases"])
        first = failed.details["first_mismatch"]
        self.assertEqual((first["case_id"], first["step"], first["signal"]),
                         (case_id, step, signal))
        self.assertEqual((first["expected_bits_value"], first["actual_bits_value"]),
                         (expected_bits, actual_bits))

    def test_shift_direction_pair(self):
        task = self.task(
            "Implement a four-bit shift register. The synchronous reset clears q only "
            "at a rising clock edge, and on each rising edge d shifts into the low end of q."
        )
        suite = shift_direction_suite(task)
        correct = """
module TopModule(input clk, input reset, input d, output reg [3:0] q);
    always @(posedge clk) begin
        if (reset) q <= 4'b0000;
        else       q <= {q[2:0], d};
    end
endmodule
"""
        wrong = """
module TopModule(input clk, input reset, input d, output reg [3:0] q);
    always @(posedge clk) begin
        if (reset) q <= 4'b0000;
        else       q <= {d, q[3:1]};
    end
endmodule
"""
        # step 1: correct 0001, wrong 1000.
        self.assert_pair(task, suite, correct, wrong, case_id="shift_in_path",
                         step=1, signal="q", expected_bits=1, actual_bits=8)

    def test_sync_reset_pair(self):
        task = self.task(
            "Implement a four-bit counter. The synchronous reset clears q only at a "
            "rising clock edge, and q holds when reset rises without a clock edge."
        )
        suite = sync_reset_suite(task)
        correct = """
module TopModule(input clk, input reset, output reg [3:0] q);
    always @(posedge clk) begin
        if (reset) q <= 4'b0000;
        else       q <= q + 4'b0001;
    end
endmodule
"""
        wrong = """
module TopModule(input clk, input reset, output reg [3:0] q);
    always @(posedge clk or posedge reset) begin
        if (reset) q <= 4'b0000;
        else       q <= q + 4'b0001;
    end
endmodule
"""
        # step 2 has no clock edge: the async reset clears q while the correct RTL holds 1.
        self.assert_pair(task, suite, correct, wrong,
                         case_id="reset_off_edge_must_hold", step=2, signal="q",
                         expected_bits=1, actual_bits=0)

    def test_unrelated_output_pair(self):
        task = self.task("Implement combinational outputs o1 is a AND b and o2 is c XOR d.")
        suite = unrelated_output_suite(task)
        correct = """
module TopModule(input a, input b, input c, input d, output o1, output o2);
    assign o1 = a & b;
    assign o2 = c ^ d;
endmodule
"""
        wrong = """
module TopModule(input a, input b, input c, input d, output o1, output o2);
    assign o1 = a & b;
    assign o2 = a & c;
endmodule
"""
        self.assert_pair(task, suite, correct, wrong, case_id="o2_case",
                         step=1, signal="o2", expected_bits=1, actual_bits=0)


if __name__ == "__main__":
    unittest.main()
