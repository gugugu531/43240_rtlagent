"""题集转换与筛选的契约测试，不运行模型或Vivado。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
from datasets import rename, rtllm_testbench, convert_chipbench, module_names, check_task
from validate_datasets import mutant, fingerprint
from balance_datasets import balanced_selection, annotate, mutation_rejected, eligibility
from archxbench_adapter import sbox_byte


class DatasetTests(unittest.TestCase):
    def test_rename_preserves_comments_and_strings(self):
        source='module old; // old\ninitial $display("old"); /* old */ endmodule'
        self.assertEqual(rename(source,{'old':'new'}),
                         'module new; // old\ninitial $display("old"); /* old */ endmodule')

    def test_no_prompt_prose_in_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);group=root/'Verilog Gen/dataset_not_self_contain';group.mkdir(parents=True)
            (group/'prob_prompt.txt').write_text('Implement a module named TopModule. Here is a helper:\nmodule helper(input a, output b); assign b=a; endmodule')
            (group/'prob_ref.sv').write_text('module RefModule(input a,output b); helper h(a,b); endmodule')
            (group/'prob_test.sv').write_text('module tb; initial $display("Mismatches: 0 in 1 samples"); endmodule')
            rows=convert_chipbench(root,root/'out');path=root/'out'/rows[0]['task_id']
            reference=(path/'ref.sv').read_text();solution=(path/'reference/solution.sv').read_text()
            self.assertNotIn('Here is',reference)
            self.assertEqual(set(module_names(reference)),{'RefModule','reference_helper'})
            self.assertEqual(set(module_names(solution)),{'TopModule','solution_helper'})
            self.assertFalse(check_task(path))

    def test_upstream_error_before_unconditional_pass_is_retained(self):
        source='''module testbench;
initial begin
 if (1) $display("Failed at check %d", 1);
 $display("=========== Your Design Passed ===========");
end
endmodule'''
        adapted=rtllm_testbench(source,'design')
        self.assertIn('tb.benchmark_error = 1',adapted)
        self.assertIn('!passed || benchmark_error != 0',adapted)
        self.assertIn('Mismatches: 1 in 0 samples',adapted)

    def test_unknown_exit_contract_fails_closed(self):
        with self.assertRaises(ValueError):
            rtllm_testbench('module t; initial $display("OK"); endmodule','dut')

    def test_mutant_finds_top_after_helper(self):
        code='module helper(input a,output b);assign b=a;endmodule\nmodule TopModule #(parameter W=8)(input clk,output [W-1:0] q);assign q=1;endmodule'
        result=mutant(code,'x')
        self.assertIn("assign q = 'x;",result)
        self.assertNotIn('module helper',result)
        self.assertIn('parameter W=8',result)

    def test_compile_failure_is_not_functional_rejection(self):
        self.assertFalse(mutation_rejected(dict(level=0,mismatches=None)))
        self.assertFalse(mutation_rejected(dict(level=2,mismatches=0)))
        self.assertFalse(mutation_rejected(dict(level=1,mismatches=3,tool_error='environment')))
        self.assertTrue(mutation_rejected(dict(level=1,mismatches=3)))
        self.assertTrue(mutation_rejected(dict(level=1,sim_timeout=True)))

    def test_incomplete_or_changed_fixture_cannot_use_old_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            (path/'tb.sv').write_text('original')
            row=dict(task_id='test',format_errors=[])
            validation=dict(complete=False,fingerprint=fingerprint(path),
                            reference=dict(level=3),mutants={k:dict(level=1,mismatches=1) for k in ('zero','unknown')})
            self.assertIn('validation_incomplete',eligibility(row,path,validation))
            validation['complete']=True
            self.assertEqual(eligibility(row,path,validation),[])
            (path/'tb.sv').write_text('changed')
            self.assertIn('validation_stale',eligibility(row,path,validation))

    def test_balanced_feasible_marginals_and_determinism(self):
        rows=[dict(task_id=f'{c}-{d}-{i}',category=c,difficulty=d,dataset='test')
              for c in ['logic','fsm','arithmetic'] for d in ['basic','intermediate','advanced'] for i in range(5)]
        selected=balanced_selection(rows,18)
        self.assertEqual(selected,balanced_selection(list(reversed(rows)),18))
        self.assertEqual(len({r['task_id'] for r in selected}),18)
        for field,values in [('category',['logic','fsm','arithmetic']),('difficulty',['basic','intermediate','advanced'])]:
            self.assertEqual([sum(r[field]==v for r in selected) for v in values],[6,6,6])

    def test_sparse_cells_not_fabricated(self):
        rows=[dict(task_id=str(i),category='logic',difficulty='basic',dataset='test') for i in range(20)]
        rows.append(dict(task_id='aes',category='crypto',difficulty='advanced',dataset='test'))
        selected=balanced_selection(rows,9)
        self.assertEqual(len(selected),9)
        self.assertIn('aes',[r['task_id'] for r in selected])

    def test_primary_function_not_implementation_keyword(self):
        self.assertEqual(annotate('rtllm_float_multi','Clock synchronization; a counter and FSM.')['category'],'arithmetic')
        self.assertEqual(annotate('example_ex01_popcount8','Count bits.')['category'],'arithmetic')
        self.assertEqual(annotate('archxbench_level_3_newton_raphson_sqrt','A finite state machine.')['category'],'arithmetic')

    def test_aes_sbox_known_values(self):
        self.assertEqual(sbox_byte(0),0x63)
        self.assertEqual(sbox_byte(0x53),0xed)


if __name__=='__main__': unittest.main()
