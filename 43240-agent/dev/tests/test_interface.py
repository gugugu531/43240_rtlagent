from __future__ import annotations

from pathlib import Path
import sys
import unittest


AGENT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from agent.core.interface import (  # noqa: E402
    check_interface_result,
    parse_module_interface,
    parse_prompt_interface,
)
from agent.core.task import TaskSpec

def infer_top(interface, prompt=""):
    return TaskSpec.from_text("test", prompt, interface).top  # noqa: E402


class ModuleInterfaceParserTests(unittest.TestCase):
    def test_parses_parameterized_ansi_ports_and_inherited_width(self):
        spec = parse_module_interface(
            "module Top #(parameter W = 8) ("
            "input logic [7:0] a, b, output reg q); endmodule"
        )

        self.assertTrue(spec.parsed)
        self.assertEqual(spec.module_name, "Top")
        self.assertEqual(
            [(port.name, port.direction, port.width) for port in spec.ports],
            [("a", "input", 8), ("b", "input", 8), ("q", "output", 1)],
        )

    def test_parses_classic_non_ansi_ports_in_header_order(self):
        spec = parse_module_interface(
            "module Top(a, b, q);\n"
            "input [7:0] a, b;\n"
            "output q;\n"
            "endmodule"
        )

        self.assertEqual(
            [(port.name, port.direction, port.width) for port in spec.ports],
            [("a", "input", 8), ("b", "input", 8), ("q", "output", 1)],
        )

    def test_symbolic_width_is_explicit_instead_of_assumed_one_bit(self):
        spec = parse_module_interface(
            "module Top #(parameter W=8) (input [W-1:0] a, output q);"
        )

        self.assertIsNone(spec.ports[0].width)
        self.assertEqual(spec.ports[0].range_text, "W-1:0")
        self.assertEqual(spec.confidence, "medium")
        self.assertTrue(spec.warnings)

    def test_malformed_nonempty_interface_is_an_explicit_parse_error(self):
        result = check_interface_result(
            "module Top(input a); endmodule",
            "module Top(input a",
        )

        self.assertEqual(result.status, "parse_error")
        self.assertTrue(result.blocking)
        self.assertEqual(result.rc, 1)


class InterfaceCheckTests(unittest.TestCase):
    def test_top_name_uses_interface_then_prompt_then_default(self):
        prompt = (
            "Implement a module named CustomTop with the following interface.\n"
            " - input a\n"
            " - output q\n"
        )

        self.assertEqual(infer_top("module FileTop(input a);", prompt), "FileTop")
        self.assertEqual(infer_top("", prompt), "CustomTop")
        self.assertEqual(infer_top("", "No interface is provided."), "TopModule")

    def test_interface_file_mismatch_is_blocking_and_structured(self):
        result = check_interface_result(
            "module Top(input [6:0] a, output q); endmodule",
            "module Top(input [7:0] a, output q);",
        )

        self.assertEqual(result.status, "mismatch")
        self.assertTrue(result.blocking)
        self.assertEqual(result.differences[0].kind, "width")
        self.assertEqual(result.differences[0].port_name, "a")
        self.assertEqual(result.expected.source, "interface_file")

    def test_prompt_difference_remains_advisory(self):
        prompt = (
            "Implement a module named TopModule with the following interface.\n"
            " - input a\n"
            " - input q\n"
        )
        result = check_interface_result(
            "module TopModule(input a, output q); endmodule", "", prompt
        )

        self.assertEqual(result.status, "advisory")
        self.assertFalse(result.blocking)
        self.assertEqual(result.differences[0].kind, "direction")
        self.assertEqual(result.expected.source, "prompt_list")

    def test_missing_expectation_is_reported_as_skipped(self):
        result = check_interface_result(
            "module TopModule; endmodule", "", "Describe a useful circuit."
        )

        self.assertEqual(result.status, "skipped")
        self.assertFalse(result.blocking)
        self.assertTrue(result.expected.warnings)


class PublicPromptRegressionTests(unittest.TestCase):
    def _prompt(self, task: str) -> str:
        return (REPO_ROOT / "tasks" / task / "prompt.txt").read_text()

    def test_public_port_list_examples(self):
        cases = {
            "Prob113_2012_q1g": [("x", "input", 4), ("f", "output", 1)],
            "Prob050_kmap1": [
                ("a", "input", 1),
                ("b", "input", 1),
                ("c", "input", 1),
                ("out", "output", 1),
            ],
            "Prob131_mt2015_q4": [
                ("x", "input", 1),
                ("y", "input", 1),
                ("z", "output", 1),
            ],
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                spec = parse_prompt_interface(self._prompt(task))
                actual = [
                    (port.name, port.direction, port.width) for port in spec.ports
                ]
                self.assertEqual(spec.module_name, "TopModule")
                self.assertEqual(actual, expected)

    def test_bugfix_source_is_not_mistaken_for_an_authoritative_spec(self):
        tasks = (
            "Prob062_bugs_mux2",
            "Prob123_bugs_addsubz",
            "Prob132_always_if2",
        )
        for task in tasks:
            with self.subTest(task=task):
                spec = parse_prompt_interface(self._prompt(task))
                self.assertFalse(spec.parsed)
                self.assertEqual(spec.ports, ())
                self.assertTrue(any("embedded module" in item for item in spec.warnings))

    def test_known_prompt_direction_error_stays_non_blocking(self):
        prompt = self._prompt("Prob031_dff")
        source = (
            REPO_ROOT / "tasks" / "Prob031_dff" / "reference" / "solution.sv"
        ).read_text()

        result = check_interface_result(source, "", prompt)

        self.assertEqual(result.status, "advisory")
        self.assertFalse(result.blocking)
        self.assertTrue(any(item.kind == "direction" for item in result.differences))

    def test_all_public_prompt_parse_exceptions_are_intentional_bugfix_tasks(self):
        unparsed = set()
        for path in sorted((REPO_ROOT / "tasks").glob("*/prompt.txt")):
            spec = parse_prompt_interface(path.read_text())
            if not spec.parsed:
                unparsed.add(path.parent.name)

        self.assertEqual(unparsed, {
            "Prob062_bugs_mux2",
            "Prob123_bugs_addsubz",
            "Prob132_always_if2",
        })

    def test_all_public_reference_module_headers_parse(self):
        failures = {}
        paths = sorted((REPO_ROOT / "tasks").glob("*/reference/solution.sv"))
        for path in paths:
            spec = parse_module_interface(path.read_text())
            if not spec.parsed:
                failures[path.parent.parent.name] = spec.warnings

        self.assertTrue(paths)
        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
