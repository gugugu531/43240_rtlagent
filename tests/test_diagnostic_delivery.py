"""Synthetic diagnostic delivery regressions; no model or EDA tool required."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from agent.rtl.adaptive_repair import repair_request
from agent.rtl.vivado import (
    classify_functional_failure,
    classify_tool_failure,
    extract_diagnostics,
    knowledge_details,
    summarize_log,
)


class DiagnosticDeliveryTests(unittest.TestCase):
    def test_warning_survives_errors_and_reaches_repair_with_provenance(self):
        log = (
            'INFO: [VRFC 10-311] analyzing module TopModule\n'
            "WARNING: [VRFC 10-8497] literal value 'd4 truncated to fit in 2 bits [solution.sv:3]\n"
            'ERROR: [VRFC 10-1280] procedural assignment to a non-register flag is not permitted [solution.sv:7]\n'
        )
        diagnostics = extract_diagnostics(log)
        self.assertEqual([item['severity'] for item in diagnostics['items']], ['warning', 'error'])
        self.assertEqual([item['line_number'] for item in diagnostics['items']], [2, 3])
        self.assertEqual(diagnostics['omitted'], 0)
        self.assertTrue(diagnostics['complete'])
        self.assertIn('VRFC 10-8497', summarize_log(log))
        self.assertIn('1 other log lines omitted', summarize_log(log))
        failure = dict(status='failed', failure_kind='code', excerpt=summarize_log(log),
                       details={'repair_diagnostics': diagnostics, **knowledge_details([
                           (('/synthetic/xvlog', '--sv', 'solution.sv'), log, 'failed', 1)
                       ])})
        original = deepcopy(failure)
        messages = repair_request(
            SimpleNamespace(prompt='Synthetic task', interface='', top='TopModule'),
            SimpleNamespace(id='c001', code_hash='synthetic', code='module TopModule; endmodule'),
            {'failure': failure},
        )
        delivered = json.loads(messages[-1]['content'])['evidence']['failure']['diagnostics']
        self.assertEqual(len(delivered['items']), 2)
        self.assertEqual(delivered['items'][0]['code'], 'VRFC 10-8497')
        self.assertEqual(delivered['items'][0]['command_index'], 0)
        self.assertEqual(delivered['items'][0]['line_number'], 2)
        self.assertEqual(failure, original)

    def test_all_severities_and_uncoded_failures_are_distinct(self):
        log = '\n'.join([
            'WARNING: [Tool 1-2] same message',
            'ERROR: [Tool 1-2] same message',
            'CRITICAL WARNING: [Tool 1-2] same message',
            'FATAL: unexpected simulator termination',
            'WARNING: [Tool 1-2] same message',
        ])
        result = extract_diagnostics(log)
        self.assertEqual([item['severity'] for item in result['items']],
                         ['warning', 'error', 'critical warning', 'fatal'])
        self.assertIsNone(result['items'][-1]['code'])
        self.assertEqual(result['duplicates'], 1)
        self.assertTrue(result['complete'])
        for diagnostic in log.splitlines():
            self.assertIn(diagnostic, summarize_log(log))

    def test_limits_do_not_claim_complete_or_hide_severity_counts(self):
        log = '\n'.join(['WARNING: [Tool 1-1] early warning',
                         'ERROR: [Tool 1-2] first error',
                         'ERROR: [Tool 1-3] later error',
                         'ERROR: [Tool 1-3] later error'])
        result = extract_diagnostics(log, limit=2)
        self.assertEqual([item['code'] for item in result['items']], ['TOOL 1-1', 'TOOL 1-2'])
        self.assertEqual((result['omitted'], result['duplicates']), (1, 1))
        self.assertFalse(result['complete'])
        zero = extract_diagnostics(log, limit=0)
        self.assertEqual(zero['items'], [])
        self.assertEqual(zero['omitted'], 3)
        self.assertFalse(zero['complete'])
        self.assertEqual(extract_diagnostics(log, limit=-2), zero)

    def test_message_and_summary_truncation_are_explicit(self):
        result = extract_diagnostics('WARNING: [Tool 1-1] ' + 'x' * 701)
        self.assertEqual(len(result['items'][0]['message']), 700)
        self.assertTrue(result['items'][0]['message_truncated'])
        self.assertEqual(result['truncated'], 1)
        self.assertFalse(result['complete'])
        self.assertTrue(extract_diagnostics('ERROR: [Tool 1-1] ' + 'x' * 700)['complete'])
        summary = summarize_log('INFO: ordinary line\nERROR: [Tool 1-1] ' + 'x' * 30, budget=20)
        self.assertIn('[truncated,', summary)
        self.assertIn('1 other log lines omitted', summary)
        tail = summarize_log('\n'.join(f'line {index}' for index in range(41)))
        self.assertNotIn('line 0\n', tail)
        self.assertIn('1 other log lines omitted', tail)

    def test_command_limits_preserve_origin_and_account_for_all_omissions(self):
        result = knowledge_details([
            (('/bin/xvlog',), 'xvlog v2026.1\nWARNING: [Tool 1-1] first', 'ok', 0),
            (('/bin/xelab',), 'ERROR: [Tool 1-2] second\nERROR: [Tool 1-3] third', 'failed', 1),
        ], limit=2)
        diagnostics = result['knowledge_diagnostics']
        self.assertEqual([(item['command_index'], item['line_number'])
                          for item in diagnostics['items']], [(0, 2), (1, 1)])
        self.assertEqual(diagnostics['items'][0]['version'], '2026.1')
        self.assertIsNone(diagnostics['items'][1]['version'])
        self.assertEqual(diagnostics['omitted'], 1)
        self.assertFalse(diagnostics['complete'])

    def test_delivery_does_not_promote_warnings_or_unknown_errors_to_code_failure(self):
        warning = "WARNING: [VRFC 10-8497] literal value 'd4 truncated to fit in 2 bits [solution.sv:3]"
        self.assertEqual(classify_tool_failure(warning), 'unknown')
        self.assertEqual(classify_functional_failure(warning), 'unknown')
        source_error = 'ERROR: [VRFC 10-1280] procedural assignment to a non-register flag is not permitted'
        self.assertEqual(classify_tool_failure(warning + '\n' + source_error), 'code')
        self.assertEqual(classify_tool_failure(source_error + '\nERROR: license unavailable'), 'environment')
        self.assertEqual(classify_tool_failure('ERROR: [Tool 1-4] unidentified problem'), 'unknown')
        clean = extract_diagnostics('INFO: successful analysis')
        self.assertEqual(clean['items'], [])
        self.assertTrue(clean['complete'])


if __name__ == '__main__':
    unittest.main()
