"""Own-tool feedback and conservative warning repair; no paid API or hidden TB."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.services.repair_feedback import (extract_diagnostics, assignment_hints,
    tool_repair_feedback, output_driver_warnings, driver_repair_improves)
from agent.services.vivado import _build_result, _CommandOutcome, classify_tool_failure
from agent.core.state import CheckResult
from agent.workflows.evidence_repair import EvidenceRepair
from agent.workflows.evidence_ablation import EvidenceInitial, EvidenceStructured, EvidenceGuided
from agent.workflows.search_ablation import SearchRepairOnce, SearchRepairTwice, SearchTwoCandidates
from support import FakeBackend, reply, run_repair, tool_result, events

BAD = 'module TopModule(input a, output logic y); logic missing; endmodule\n'
GOOD = 'module TopModule(input a, output y); assign y=a; endmodule\n'
WARN = 'WARNING: [Synth 8-3848] Net y in module/entity TopModule does not have driver.'
ERROR = "ERROR: [VRFC 10-3818] variable 'y' is driven by invalid combination of procedural drivers [/tmp/solution.sv:2]"


def synth_check(code, text, *, details=True, status='passed'):
    return CheckResult(code, code, 'synth', status, text,
                       details={'repair_diagnostics': extract_diagnostics(text)} if details else {})


class DriverTools:
    def __init__(self, *, complete=True, synth_status='ok'):
        self.complete, self.synth_status, self.calls = complete, synth_status, []

    def lint(self, code, top, timeout_s):
        self.calls.append(('lint', code))
        return tool_result('lint', 'failed' if 'broken' in code else 'ok',
                           ERROR if 'broken' in code else 'lint ok')

    def synth(self, code, top, timeout_s):
        self.calls.append(('synth', code))
        text = WARN if 'missing' in code else 'Synthesis finished'
        details = {'repair_diagnostics': extract_diagnostics(text)}
        if 'missing' not in code and not self.complete:
            details = {}
        return replace(tool_result('synth', self.synth_status, text), details=details)


class FeedbackEvidenceTests(unittest.TestCase):
    def test_invalid_driver_root_is_code_but_trailer_and_environment_are_not(self):
        self.assertEqual(classify_tool_failure(ERROR), 'code')
        self.assertEqual(classify_tool_failure('ERROR: [XSIM 43-3322] Static elaboration failed'), 'unknown')
        self.assertEqual(classify_tool_failure('ERROR: [VRFC 10-3818] unfamiliar diagnostic'), 'unknown')
        for suffix in ('No space left on device', 'license expired', 'permission denied'):
            self.assertEqual(classify_tool_failure(ERROR + '\n' + suffix), 'environment')

    def test_root_collection_precedes_human_summary_truncation(self):
        text = ERROR + '\n' + 'ERROR: [VRFC 10-1] ' + 'x' * 2200 + '\n' + ERROR.replace("'y'", "'flag'")
        result = _build_result('lint', [_CommandOutcome(('xelab',), 1, 'failed', .1, text)], '/tmp', False)
        self.assertNotIn("'flag'", result.summary)
        self.assertEqual(result.details['repair_diagnostics']['items'][-1]['symbols'], ['flag'])
        check = CheckResult('k1', 'c1', 'lint', 'failed', result.summary, details=result.details)
        feedback = tool_repair_feedback('module TopModule; endmodule', [check])
        self.assertIn("variable 'flag'", feedback)
        self.assertIn('Diagnostic evidence incomplete', feedback)

    def test_duplicates_cascades_and_limits_are_explicit(self):
        trailer = 'ERROR: [XSIM 43-3322] Static elaboration failed'
        rows = extract_diagnostics(ERROR + '\n' + ERROR + '\n' + trailer)
        self.assertEqual(len(rows['items']), 2)
        self.assertTrue(rows['items'][-1]['cascade'])
        self.assertTrue(rows['complete'])
        self.assertFalse(extract_diagnostics(ERROR + '\n' + trailer, limit=1)['complete'])
        self.assertEqual(extract_diagnostics(ERROR + '\n' + trailer, limit=1)['omitted'], 1)

    def test_assignment_hints_include_reset_and_indexed_concatenated_lhs(self):
        code = ('module TopModule;\n'
                'always_ff @(posedge clk) if (rst) y <= 0;\n'
                'always_comb begin\n'
                ' y[0] = a;\n'
                ' {y[1], flag} = b;\n'
                ' if (y <= a) other = y;\n'
                ' // y = 3;\n'
                ' $display("y = 4;");\n'
                'end\nendmodule\n')
        self.assertEqual([s['line'] for s in assignment_hints(code, 'y')], [2, 4, 5])
        check = CheckResult('k1', 'c1', 'lint', 'failed', ERROR,
                            details={'repair_diagnostics': extract_diagnostics(ERROR)})
        feedback = tool_repair_feedback(code, [check])
        self.assertIn('Reset-only writes COUNT as drivers', feedback)
        self.assertIn('3 write sites', feedback)
        self.assertIn('lexical', feedback)

    def test_only_known_top_outputs_in_successful_complete_synthesis_are_actionable(self):
        others = ('WARNING: [Synth 8-3848] Net a in module/entity TopModule does not have driver.\n'
                  'WARNING: [Synth 8-3848] Net internal in module/entity TopModule does not have driver.\n'
                  'WARNING: [Synth 8-3848] Net y in module/entity Helper does not have driver.')
        check = synth_check('c1', WARN + '\n' + others)
        self.assertEqual([w['signal'] for w in output_driver_warnings(BAD, 'TopModule', [check])], ['y'])
        for unknown in (replace(check, status='timeout'), replace(check, details={}),
                        replace(check, details={'repair_diagnostics': extract_diagnostics(WARN, limit=0)})):
            self.assertEqual(output_driver_warnings(BAD, 'TopModule', [unknown]), [])
        self.assertEqual(output_driver_warnings(BAD, 'Other', [check]), [])

    def test_strict_improvement_requires_complete_observation_and_identical_interface(self):
        old, clean = synth_check('old', WARN), synth_check('new', '')
        self.assertTrue(driver_repair_improves(BAD, GOOD, 'TopModule', [old], [clean]))
        for changed in (GOOD.replace('output y', 'output z'), GOOD.replace('input a', 'input b'),
                        GOOD.replace('output y', 'output [1:0] y')):
            self.assertFalse(driver_repair_improves(BAD, changed, 'TopModule', [old], [clean]))
        for incomplete in (replace(clean, status='timeout'), replace(clean, details={}),
                           synth_check('new', 'WARNING: [Synth 8-3848] Unfamiliar warning format'),
                           replace(clean, details={'repair_diagnostics': dict(items=[], complete=False, omitted=1)})):
            self.assertFalse(driver_repair_improves(BAD, GOOD, 'TopModule', [old], [incomplete]))
        self.assertFalse(driver_repair_improves(BAD, GOOD, 'TopModule', [old], [old]))

    def test_vector_bit_warnings_do_not_disappear_by_collapsing_signal_names(self):
        code = 'module TopModule(input a, output [1:0] y); endmodule'
        bit0, bit1 = WARN.replace('Net y ', 'Net y[0] '), WARN.replace('Net y ', 'Net y[1] ')
        old = synth_check('old', bit0 + '\n' + bit1)
        self.assertTrue(driver_repair_improves(code, code, 'TopModule', [old], [synth_check('new', bit1)]))
        self.assertFalse(driver_repair_improves(code, code, 'TopModule', [synth_check('old', bit0)],
                                               [synth_check('new', bit1)]))


class DriverWorkflowTests(unittest.TestCase):
    def test_stronger_interface_rank_cannot_bypass_warning_repair_protection(self):
        from agent.core.candidate import CandidateFactory
        from agent.core.state import RunStateView
        from agent.workflows.repair_loop import RepairLoop
        factory = CandidateFactory()
        first = factory.create(BAD, source_stage='generate', round=1)
        second = factory.create(GOOD.replace('input a', 'input b'), source_stage='repair', round=2)
        checks = (CheckResult('l1', first.id, 'lint', 'passed', ''),
                  replace(synth_check(first.id, WARN), id='s1'),
                  CheckResult('i2', second.id, 'interface', 'passed', ''),
                  CheckResult('l2', second.id, 'lint', 'passed', ''),
                  replace(synth_check(second.id, ''), id='s2'))
        workflow = RepairLoop(use_skills=False)
        workflow._output_top = 'TopModule'
        state = RunStateView({c.id: c for c in (first, second)}, checks, (), first.id, None)
        self.assertEqual(workflow.choose(state).candidate_id, first.id)

    def test_warning_repair_is_bounded_and_verified_before_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = DriverTools()
            backend = FakeBackend([reply(BAD), reply(GOOD)])
            result = run_repair(temp, backend, tools, max_rounds=2, max_request_retries=0)
            self.assertEqual(result.selected_candidate.code, GOOD)
            self.assertEqual(len(backend.requests), 2)
            self.assertIn('TOP-LEVEL OUTPUTS', backend.requests[1].messages[-1]['content'])
            self.assertEqual([kind for kind, _ in tools.calls], ['lint', 'synth', 'lint', 'synth'])
            trace = events(temp)
            improved = next(i for i, e in enumerate(trace) if e.get('reason') == 'output_driver_improved')
            synth = next(i for i, e in enumerate(trace) if e['tool'] == 'synth' and e.get('candidate_id') == 'c002')
            self.assertGreater(improved, synth)
            warning = next(e for e in trace if e.get('event') == 'synthesis_output_warning')
            self.assertFalse(warning['functional_verified'])

    def test_failed_uncleared_or_interface_changed_repair_preserves_parent(self):
        for proposed in (BAD.replace('logic missing', 'logic missing, extra'),
                         GOOD.replace('assign y=a', 'wire broken; assign y=a'),
                         GOOD.replace('input a', 'input b')):
            with self.subTest(proposed=proposed), tempfile.TemporaryDirectory() as temp:
                result = run_repair(temp, FakeBackend([reply(BAD), reply(proposed)]), DriverTools(),
                                    max_rounds=2, max_request_retries=0)
                self.assertEqual(result.selected_candidate.code, BAD)

    def test_missing_new_diagnostics_retains_parent_and_records_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, FakeBackend([reply(BAD), reply(GOOD)]), DriverTools(complete=False),
                                max_rounds=2, max_request_retries=0)
            self.assertEqual(result.selected_candidate.code, BAD)
            self.assertEqual(result.stop_reason, 'warning_repair_unverified')

    def test_no_extra_call_when_round_budget_is_exhausted_or_feature_disabled(self):
        for params in (dict(max_rounds=1), dict(max_rounds=3, repair_output_drivers=False)):
            with self.subTest(params=params), tempfile.TemporaryDirectory() as temp:
                backend = FakeBackend([reply(BAD)])
                result = run_repair(temp, backend, DriverTools(), max_request_retries=0, **params)
                self.assertEqual(len(backend.requests), 1)
                self.assertEqual(result.selected_candidate.code, BAD)

    def test_synthesis_failure_does_not_trigger_warning_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend([reply(BAD)])
            result = run_repair(temp, backend, DriverTools(synth_status='timeout'), max_rounds=2)
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(result.stop_reason, 'timeout')

    def test_existing_evidence_and_search_experiments_keep_warning_trigger_disabled(self):
        for workflow in (EvidenceRepair, EvidenceInitial, EvidenceStructured, EvidenceGuided,
                         SearchRepairOnce, SearchRepairTwice, SearchTwoCandidates):
            with self.subTest(workflow=workflow):
                self.assertFalse(workflow().repair_output_drivers)


@unittest.skipUnless(os.environ.get('RUN_VIVADO_TESTS') == '1', 'set RUN_VIVADO_TESTS=1 for real Vivado')
class RealVivadoDriverTests(unittest.TestCase):
    def run_workflow(self, first, fixed, interface='module TopModule(input a, output y);'):
        from agent.core.config import ModelConfig, ToolConfig
        from agent.core.task import TaskSpec
        from agent.core.registry import build_workflow
        from agent.core.runner import Runner, RunOptions
        task = TaskSpec.from_text('driver-regression', 'Outputs equal input a.', interface)
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend([reply(first), reply(fixed)])
            result = Runner(ModelConfig(), backend_factory=lambda _: backend,
                tool_config=ToolConfig(bin_dir=os.environ['VIVADO_BIN'], temp_dir=temp)).run(
                    task, lambda: build_workflow('repair_loop', max_rounds=2, use_skills=False,
                                               max_request_retries=0),
                    options=RunOptions(Path(temp) / 'output', deadline_s=300, reserve_s=10))
            trace = events(Path(temp) / 'output')
            diagnostics = [(e['tool'], e.get('status'), e.get('excerpt'), e.get('details'))
                           for e in trace if e['tool'] in ('lint', 'synth')]
            self.assertEqual(result.selected_candidate.code, fixed, (result.stop_reason, diagnostics))
            self.assertEqual(len(backend.requests), 2)
            return trace

    def test_real_undriven_warning_repair_has_verified_synthesis_improvement(self):
        # Keep one output live: an entirely empty design may fail synthesis before
        # a complete warning observation, which must not be treated as repairable.
        first = 'module TopModule(input a, output logic y, output z); assign z=a; endmodule\n'
        fixed = first.replace('endmodule', 'assign y=a; endmodule')
        trace = self.run_workflow(first, fixed, 'module TopModule(input a, output y, output z);')
        self.assertTrue(any(e.get('reason') == 'output_driver_improved' for e in trace))
        self.assertTrue(any(e['tool'] == 'synth' and e['status'] == 'passed' and
                            e.get('candidate_id') == 'c002' for e in trace))

    def test_real_invalid_procedural_drivers_trigger_compile_repair(self):
        first = ('module TopModule(input a, output logic y); '
                 'always_comb y=a; initial y=0; endmodule\n')
        trace = self.run_workflow(first, GOOD)
        failure = next(e for e in trace if e['tool'] == 'lint' and e['status'] == 'failed')
        self.assertEqual(failure['details']['failure_kind'], 'code')
        self.assertTrue(any(d['code'] == 'VRFC 10-3818' for d in
                            failure['details']['repair_diagnostics']['items']))


if __name__ == '__main__':
    unittest.main()
