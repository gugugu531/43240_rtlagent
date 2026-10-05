from __future__ import annotations

from pathlib import Path
import sys
import unittest


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.nodes.extraction import extract_code, extract_result  # noqa: E402


class ExtractionTests(unittest.TestCase):
    def test_prefers_longest_fenced_block(self):
        text = """Interface:
```verilog
module TopModule(); endmodule
```
Implementation:
```systemverilog
module TopModule(input a, output q);
  assign q = a;
endmodule
```
"""
        self.assertEqual(
            extract_code(text),
            "module TopModule(input a, output q);\n"
            "  assign q = a;\n"
            "endmodule\n",
        )

    def test_accepts_unfenced_module(self):
        code = "module TopModule;\nendmodule"
        self.assertEqual(extract_code(code), code + "\n")

    def test_rejects_prose_without_complete_module(self):
        self.assertEqual(extract_code("I would write a module here."), "")

    def test_prefers_target_module_over_longer_wrong_block(self):
        text = """```verilog
module WrongModule(input a, output q);
  wire padding_padding_padding_padding;
  assign q = a;
endmodule
```
```sv
module TopModule(input a, output q);
  assign q = a;
endmodule
```
"""
        result = extract_result(text, target_module="TopModule")

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.target_module_found)
        self.assertEqual(result.module_names, ("TopModule",))
        self.assertTrue(result.multiple_blocks)
        self.assertIn("module TopModule", result.code)
        self.assertNotIn("WrongModule", result.code)

    def test_keeps_auxiliary_modules_in_selected_block(self):
        text = """Explanation before the code.
```systemverilog
module helper(input a, output q);
  assign q = a;
endmodule

module TopModule(input a, output q);
  helper u_helper(.a(a), .q(q));
endmodule
```
Explanation after the code.
"""
        result = extract_result(text, target_module="TopModule")

        self.assertTrue(result.complete)
        self.assertEqual(result.module_names, ("helper", "TopModule"))
        self.assertIn("module helper", result.code)
        self.assertIn("module TopModule", result.code)

    def test_reports_truncated_module_without_returning_partial_code(self):
        result = extract_result(
            "```verilog\nmodule TopModule(input a, output q);\nassign q = a;",
            target_module="TopModule",
        )

        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.complete)
        self.assertTrue(result.suspected_truncation)
        self.assertEqual(result.code, "")
        self.assertEqual(result.module_names, ("TopModule",))

    def test_reports_different_complete_target_drafts_as_ambiguous(self):
        text = """```verilog
module TopModule(input a, output q); assign q = a; endmodule
```
```verilog
module TopModule(input a, output q); assign q = ~a; endmodule
```
"""
        result = extract_result(text, target_module="TopModule")

        self.assertEqual(result.status, "ambiguous")
        self.assertTrue(result.complete)
        self.assertTrue(result.multiple_blocks)
        self.assertTrue(any("drafts" in item for item in result.diagnostics))

    def test_unfenced_reply_drops_explanation_around_module(self):
        result = extract_result(
            "Here is the implementation:\n"
            "module TopModule;\nendmodule\n"
            "This should solve the task.",
            target_module="TopModule",
        )

        self.assertEqual(result.code, "module TopModule;\nendmodule\n")
        self.assertNotIn("implementation", result.code)
        self.assertNotIn("solve", result.code)

    def test_trace_metadata_never_contains_source_code(self):
        result = extract_result(
            "```verilog\nmodule TopModule; endmodule\n```",
            target_module="TopModule",
        )

        metadata = result.trace_dict()
        self.assertNotIn("code", metadata)
        self.assertEqual(metadata["status"], "ok")
        self.assertGreater(metadata["code_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
