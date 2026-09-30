from __future__ import annotations

from pathlib import Path
import sys
import unittest


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.extraction import extract_code  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
