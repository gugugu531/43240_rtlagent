"""Prompt regressions for the single-stage stop-and-deliver repair contract."""

import unittest

from agent.prompts import TemplateRenderer
from agent.rtl.candidate import CandidateFactory
from agent.rtl.task import TaskSpec


class DeliveryStopContract(unittest.TestCase):
    def setUp(self):
        self.renderer = TemplateRenderer()
        self.task = TaskSpec.from_text(
            "delivery-stop-contract",
            "Repair the output declaration in the buggy candidate and keep its behavior.",
            "module TopModule(input a, output [1:0] y); endmodule",
        )
        self.parent = CandidateFactory().create(
            "module TopModule(input a, output y); assign y = {2{a}}; endmodule",
            source_stage="public_synthetic",
            round=1,
        )

    def render_repair(self):
        return self.renderer.render(
            "repair.j2",
            task=self.task,
            parent=self.parent,
            feedback="The public output width is two bits, but the candidate declares one bit.",
        )

    def test_system_contract_stops_and_delivers_complete_legal_rtl(self):
        system = self.render_repair()[0]["content"]
        self.assertIn("## Stop and deliver", system)
        self.assertIn("smallest", system)
        self.assertIn("stop exploring alternative architectures", system)
        self.assertIn("complete, syntactically legal RTL file", system)
        self.assertIn("must not delay delivery", system)
        self.assertIn("not a patch, fragment, or analysis note", system)

    def test_repair_contract_binds_stopping_to_supplied_evidence(self):
        user = self.render_repair()[1]["content"]
        self.assertIn("Apply a stop-and-deliver discipline", user)
        self.assertIn("smallest code location and modification", user)
        self.assertIn("unless a new public counterexample", user)
        self.assertIn("Prefer", user)
        self.assertIn("a simple intermediate signal or explicit per-bit condition", user)
        self.assertIn("Do not let unresolved optional matters block delivery", user)

    def test_authoritative_interface_allows_explicit_declaration_repair(self):
        system, user = (message["content"] for message in self.render_repair())
        self.assertIn("example explicitly described as buggy is not", system)
        self.assertIn("explicitly requires fixing a declaration", system)
        self.assertIn("A declaration explicitly identified by the public task as faulty", user)
        self.assertIn("do not preserve a known faulty width", user)

    def test_analysis_and_delivery_output_contracts_do_not_conflict(self):
        delivery = self.render_repair()
        analysis = self.renderer.render(
            "repair_analysis.j2",
            task=self.task,
            parent=self.parent,
            feedback="The candidate output width is inconsistent with the public interface.",
        )
        self.assertIn("Output exactly one fenced ```verilog code block", delivery[0]["content"])
        self.assertNotIn("exactly one JSON object", delivery[0]["content"])
        self.assertIn("exactly one JSON object", analysis[0]["content"])
        self.assertNotIn("fenced ```verilog code block", analysis[0]["content"])

    def test_stop_contract_does_not_disable_thinking_or_request_reasoning_transfer(self):
        rendered = "\n".join(message["content"] for message in self.render_repair()).lower()
        self.assertNotIn("disable thinking", rendered)
        self.assertNotIn("reasoning_content", rendered)
        self.assertNotIn("truncated reasoning", rendered)


if __name__ == "__main__":
    unittest.main()
