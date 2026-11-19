"""Clock/reset article regressions using synthetic public specifications."""

import unittest

from agent.domain.rtl.guided_checker import checker_contract
from agent.domain.rtl.task import TaskSpec


CLOCK = " Sequential logic is triggered on the positive edge of the clock."


def public_task(semantics, *, extra_clock=False):
    ports = " - input clk\n - input areset\n - input data\n - output q\n"
    if extra_clock:
        ports += " - input clk2\n"
    return TaskSpec.from_text(
        "clock_articles",
        "Implement a module named TopModule with the following interface.\n"
        + ports + semantics,
    )


class GuidedClockArticleTests(unittest.TestCase):
    def test_explicit_clock_and_reset_phrases(self):
        cases = {
            "article_a": "areset is a positive edge triggered asynchronous reset." + CLOCK,
            "article_the": "areset is the positive edge triggered asynchronous reset." + CLOCK,
            "without_article": "areset is positive edge triggered asynchronous reset." + CLOCK,
            "across_lines": "areset is a positive\nedge triggered asynchronous reset." + CLOCK,
            "uppercase": "ARESET IS A POSITIVE EDGE triggered asynchronous reset." + CLOCK,
            "hdl_positive_reset": "always @(posedge clk or posedge areset)",
            "hdl_negative_reset": "always @(posedge clk or negedge areset)",
            "clock_article": "clk is a positive edge triggered clock.",
            "possessive": "clk's rising edge captures data.",
        }
        for name, semantics in cases.items():
            with self.subTest(name=name):
                task = public_task(semantics)
                self.assertTrue(task.expected_interface.complete)
                result = checker_contract(task)
                self.assertTrue(result["supported"], result)
                self.assertEqual(result["clock"], {"port": "clk", "edge": "posedge"})

    def test_unsupported_or_locally_ambiguous_phrases(self):
        cases = {
            "unbound_subject": "A positive edge triggers the logic.",
            "reset_without_clock_edge": "areset is a positive edge triggered asynchronous reset.",
            "negative_clock": "clk is a negative edge triggered clock.",
            "hdl_negative_clock": "always @(negedge clk)",
            "both_clock_polarities": CLOCK + " Logic also uses the falling edge of clk.",
            "data_edge": "data is a positive edge triggered input." + CLOCK,
            "hdl_data_edge": "always @(posedge clk or posedge data)",
            "negated_reset": "areset is not a positive edge triggered reset." + CLOCK,
            "negated_clock": "clk is not a positive edge triggered input.",
            "uncertain_reset": "areset may be a positive edge triggered reset." + CLOCK,
            "cannot_reset": "areset cannot be a positive edge triggered reset." + CLOCK,
            "unknown_subject": "event is a positive edge triggered input." + CLOCK,
            "unspecified_edge": "The register captures data on each clock cycle.",
        }
        for name, semantics in cases.items():
            with self.subTest(name=name):
                task = public_task(semantics)
                self.assertTrue(task.expected_interface.complete)
                result = checker_contract(task)
                self.assertFalse(result["supported"], result)
                self.assertTrue(result["reason"])

    def test_multiple_clocks_remain_unsupported(self):
        task = public_task(CLOCK, extra_clock=True)
        self.assertTrue(task.expected_interface.complete)
        result = checker_contract(task)
        self.assertFalse(result["supported"], result)
        self.assertEqual(result["reason"], "multiple clock candidates are not supported")


if __name__ == "__main__":
    unittest.main()
