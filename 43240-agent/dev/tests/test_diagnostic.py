import unittest
from agent.core.diagnostic import diagnostics_from_check
from agent.core.state import CheckResult


class DiagnosticTests(unittest.TestCase):
    def check(self, summary, **details):
        return CheckResult('k1', 'c1', 'lint', 'failed', summary, details=details)

    def test_namespace_and_position_are_attributed_to_exact_tool(self):
        result = diagnostics_from_check(self.check(
            'ERROR: [VRFC 10-1280] bad assignment [/tmp/solution.sv:2:3]',
            failure_kind='code', diagnostic_tool='xvlog', tool_version='2026.1'),
            candidate_code='module TopModule;\nendmodule\n')[0]
        self.assertEqual((result.code, result.tool, result.version), ('VRFC 10-1280', 'xvlog', '2026.1'))
        self.assertEqual((result.candidate_line, result.reported_column), (2, 3))

    def test_external_or_out_of_range_location_is_not_claimed_as_candidate(self):
        for path in ('other.sv:1', 'solution.sv:900'):
            result = diagnostics_from_check(self.check(f'ERROR: [Synth 8-1] bad [{path}]'),
                                            candidate_code='module TopModule; endmodule')[0]
            self.assertIsNone(result.candidate_line)
            self.assertEqual(result.code, 'SYNTH 8-1')
            self.assertIsNone(result.tool)

    def test_environment_and_warning_never_become_code_failures(self):
        result = diagnostics_from_check(self.check('WARNING: [VRFC 10-1] text\nlicense unavailable',
                                                   failure_kind='environment'))[0]
        self.assertEqual(result.classification, 'environment')
        self.assertEqual(result.severity, 'WARNING')

    def test_unknown_failure_stays_unknown_and_duplicate_lines_are_removed(self):
        result = diagnostics_from_check(self.check('unknown failure'))[0]
        self.assertIsNone(result.code)
        line = 'ERROR: [VRFC 10-1] bad'
        self.assertEqual(len(diagnostics_from_check(self.check(line + '\n' + line))), 1)
