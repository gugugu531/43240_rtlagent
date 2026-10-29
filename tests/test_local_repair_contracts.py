"""Offline contract tests; model mocks are not evidence of repair benefit."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from agent.knowledge.admission import decide, contract, F24, GENVAR, generate_witnesses
from agent.knowledge.outcome import classify_attempt, classify_development_result
from agent.knowledge.runtime import bundle, retrieve_runtime
from agent.llm.repair_delivery import complete, validate_plan, thinking_generation
from agent.llm.types import Reply
from agent.prompts import TemplateRenderer
from agent.rtl.candidate import CandidateFactory
from agent.rtl.result import CheckResult, bind_result
from agent.rtl.task import TaskSpec
from agent.runtime.allowance import AllowanceError
from agent.runtime.budget import Budget

CODE='module TopModule(input x, input [3:0] a, output [7:0] y);\nassign y = {4{x}, a};\nendmodule'
LOOP='module Renamed #(parameter N=4)(input [N-1:0] source, output [N-1:0] dest);\ngenerate\nfor (k=0;k<N;k=k+1) begin: lanes\nassign dest[k]=source[k];\nend\nendgenerate\nendmodule'


def fixture(rtl=CODE, **changes):
    parent=CandidateFactory().create(rtl,source_stage='public_synthetic',round=1)
    item=dict(code='VRFC 10-4982',tool='xvlog',version='2026.1',severity='error',cascade=False,
              process_status='failed',message="syntax error near ',' [candidate.sv:2]",command_index=0)
    item.update(changes)
    check=bind_result(CheckResult(status='failed',summary=item['message'],failure_kind='code',
        details={'knowledge_diagnostics':{'complete':True,'items':[item]},
                 'source_binding':{'paths':['candidate.sv'],'candidate_sha256':parent.code_hash}}),parent,'lint')
    return parent,dict(check=check,execution_id='public-synthetic-execution')


def plan(parent):
    return dict(candidate_sha256=parent.code_hash,established_facts=['A comma syntax error was reported.'],
        edits=[dict(old='{4{x}, a}',new='{{4{x}}, a}',reason='Separate replication from outer concatenation.')],
        boundary_check='Compile the changed assignment.',uncertainties=[])


class Fake:
    def __init__(self, planning, *, unknown=False, fail=False):
        self.generation={'seed':1,'chat_template_kwargs':{'retained_option':True}}
        self.planning=planning;self.unknown=unknown;self.fail=fail;self.calls=[]

    @contextmanager
    def permitted(self,permit):
        self.permit=permit;permit._begin()
        try:yield
        finally:permit._finish()

    def chat(self,messages,**options):
        call_id='mock-'+str(len(self.calls));self.permit._sent(call_id,options['max_tokens'])
        self.calls.append((deepcopy(messages),deepcopy(self.generation),options))
        if self.fail:raise RuntimeError('transport failed')
        self.permit._response({'usage':None if self.unknown else {'prompt_tokens':100,'completion_tokens':20}})
        if options['purpose']=='repair_plan':return replace(self.planning,call_id=call_id)
        return Reply(call_id,'```verilog\n'+CODE.replace('{4{x}, a}','{{4{x}}, a}')+'\n```','stop',100,20)


class DeliveryContracts(unittest.TestCase):
    def setUp(self):
        self.parent,_=fixture();self.task=TaskSpec.from_text('public','Repair the malformed concatenation in module TopModule.')
        self.prompts=TemplateRenderer()
        self.messages=self.prompts.render('repair.j2',task=self.task,parent=self.parent,feedback='syntax error')
    def reply(self,value=None,finish='stop'):
        return Reply('plan',json.dumps(plan(self.parent) if value is None else value),finish,100,20,
                     reasoning={'reasoning_content':'DO NOT FORWARD THIS PRIVATE SCRATCH TEXT'})
    def context(self,llm):
        events=[]
        return NS(llm=llm,budget=Budget(900,20),record=NS(emit=lambda *a,**kw:events.append((a,kw))),
                  prompts=self.prompts,task=self.task,events=events)
    def run_delivery(self,llm):
        ctx=self.context(llm);before=deepcopy(llm.generation)
        answer,trace=complete(ctx,self.parent,'syntax error',self.messages,max_tokens=4096,timeout_s=180)
        self.assertEqual(llm.generation,before)
        return answer,trace,ctx
    def test_independent_contracts(self):
        analysis=self.prompts.render('repair_analysis.j2',task=self.task,parent=self.parent,feedback='syntax error')
        self.assertIn('exactly one JSON',analysis[0]['content'])
        self.assertNotIn('Output exactly one fenced',analysis[0]['content'])
        self.assertIn('Output exactly one fenced',self.messages[0]['content'])
        self.assertIn('buggy',self.messages[0]['content'])
    def test_both_stages_thinking_and_bounded(self):
        llm=Fake(self.reply());answer,trace,ctx=self.run_delivery(llm)
        self.assertEqual(len(llm.calls),2)
        self.assertEqual(sum(c[2]['max_tokens'] for c in llm.calls),4096)
        self.assertTrue(all(c[1]['chat_template_kwargs']['enable_thinking'] for c in llm.calls))
        self.assertTrue(all(c[1]['chat_template_kwargs']['retained_option'] for c in llm.calls))
        self.assertTrue(trace['plan_forwarded']);self.assertFalse(trace['final_delivery_guaranteed'])
        self.assertNotIn('PRIVATE SCRATCH',json.dumps(llm.calls))
        self.assertEqual(answer.call_id,'mock-1')
        self.assertEqual(ctx.events[-1][1]['allowance']['calls_sent'],2)
    def test_truncated_plan_never_forwarded_even_with_valid_json(self):
        llm=Fake(self.reply(finish='length'));_,trace,_=self.run_delivery(llm)
        self.assertFalse(trace['plan_forwarded']);self.assertEqual(llm.calls[-1][0],self.messages)
        self.assertNotIn('PRIVATE SCRATCH',json.dumps(llm.calls))
    def test_empty_final_analysis_does_not_fall_back_to_reasoning(self):
        llm=Fake(replace(self.reply(),content=''));_,trace,_=self.run_delivery(llm)
        self.assertFalse(trace['plan_forwarded']);self.assertEqual(llm.calls[-1][0],self.messages)
    def test_stale_and_ambiguous_plans(self):
        self.assertEqual(validate_plan(self.reply(),replace(self.parent,code_hash='0'*64))[1],'invalid_candidate_identity')
        value=plan(self.parent);value['candidate_sha256']='0'*64
        self.assertEqual(validate_plan(self.reply(value),self.parent)[1],'stale_plan')
        value=plan(self.parent);value['edits'][0]['old']='not in current source'
        self.assertIsNone(validate_plan(self.reply(value),self.parent)[0])
        value=plan(self.parent);value['edits'].append(dict(value['edits'][0]))
        self.assertEqual(validate_plan(self.reply(value),self.parent)[1],'overlapping_edits')
    def test_schema_and_tool_calls(self):
        value=plan(self.parent);value['hidden_answer']='forbidden'
        self.assertIsNone(validate_plan(self.reply(value),self.parent)[0])
        self.assertIsNone(validate_plan(replace(self.reply(),tool_calls=[{}]),self.parent)[0])
        self.assertIsNone(validate_plan(replace(self.reply(),content='{"x":1,"x":2}'),self.parent)[0])
    def test_unknown_usage_blocks_second_call(self):
        llm=Fake(self.reply(),unknown=True);ctx=self.context(llm);before=deepcopy(llm.generation)
        with self.assertRaises(AllowanceError):
            complete(ctx,self.parent,'',self.messages,max_tokens=4096,timeout_s=180)
        self.assertEqual(len(llm.calls),1);self.assertEqual(llm.generation,before)
    def test_transport_failure_is_not_retried(self):
        llm=Fake(self.reply(),fail=True);ctx=self.context(llm);before=deepcopy(llm.generation)
        with self.assertRaises(RuntimeError):
            complete(ctx,self.parent,'',self.messages,max_tokens=4096,timeout_s=180)
        self.assertEqual(len(llm.calls),1);self.assertEqual(llm.generation,before)
    def test_insufficient_window_prevents_calls(self):
        llm=Fake(self.reply());ctx=self.context(llm);ctx.budget=Budget(100,20)
        with self.assertRaises(AllowanceError):
            complete(ctx,self.parent,'',self.messages,max_tokens=4096,timeout_s=180)
        self.assertFalse(llm.calls)
    def test_conflicting_thinking_controls(self):
        for controls in ({'reasoning_budget':0},{'reasoning_effort':'none'},{'reasoning':'off'},
                         {'chat_template_kwargs':{'reasoning_budget':0}}):
            with self.subTest(controls=controls),self.assertRaises(ValueError):thinking_generation(controls)


class SharedAdmission(unittest.TestCase):
    def retrieve(self,p,e,**options):
        return retrieve_runtime(e,p,{'admission_policy':'evidence-v1',**options},[])
    def test_positive_is_only_eligibility(self):
        p,e=fixture();cards,t=self.retrieve(p,e)
        self.assertEqual(len(cards),1);self.assertEqual(t['empty_kind'],'not_empty')
        d=t['admission_decisions'][0]
        self.assertEqual(d['measured_benefit'],'not_established')
        self.assertEqual(len(t['admission_implementation_sha256']),64)
    def test_unknown_not_correct_empty(self):
        p,e=fixture(message="syntax error near ','")
        cards,t=self.retrieve(p,e)
        self.assertFalse(cards);self.assertEqual(t['empty_kind'],'unknown')
        self.assertNotEqual(t['reason'],'correct_empty')
    def test_redundant_feedback_and_surrounding_advice(self):
        p,e=fixture()
        for kwargs in ({'feedback':'Wrap replication in an outer concatenation.'},
                       {'supplied_messages':[{'content':'Wrap replication in an outer concatenation.'}]}):
            d=decide(F24,e,p,**kwargs)
            self.assertEqual(d['decision_class'],'not_needed')
    def test_failure_is_not_correct_empty(self):
        p,e=fixture()
        with patch('agent.knowledge.runtime.embed',side_effect=ValueError('service unavailable')):
            _,t=self.retrieve(p,e,strategy='dense')
            self.assertEqual(t['empty_kind'],'runtime_failure')
        with patch('agent.knowledge.runtime.bundle',side_effect=ValueError('asset mismatch')):
            _,t=self.retrieve(p,e)
            self.assertEqual(t['empty_kind'],'runtime_failure')
    def test_all_card_sidecars_bound_to_frozen_identity(self):
        data,_=bundle()
        for row in data['rules']+[data['f24_admission']]:
            value=contract(row['card_id'])
            self.assertEqual(value['card_sha256'],row['card_sha256'])
            self.assertEqual(value['card_version'],row['card_version'])
            self.assertTrue(value['additional_knowledge'])
            self.assertIn('redundant_when',value)
        self.assertIsNone(contract('unknown-card'))
    def test_structural_mutations_and_unknowns(self):
        for code in (LOOP,LOOP.replace('k','idx'),LOOP.replace('Renamed','OtherName'),
                     LOOP+'\nmodule unrelated; endmodule',LOOP.replace('k<N','k < N /* boundary */'),
                     LOOP.replace('N=4','N=2+2')):
            with self.subTest(code=code):self.assertEqual(len(generate_witnesses(code)),1)
        for code in (LOOP.replace('generate\n','integer k; generate\n',1),
                     LOOP.replace('k<N','k<runtime_bound'),LOOP.replace('k<N','k<`WIDTH'),
                     LOOP.replace('generate\n','always @* begin\n',1),
                     LOOP.replace('generate\n','generate if (N) begin\n',1)):
            self.assertFalse(generate_witnesses(code))
    def test_real_genvar_advice_is_not_needed_sanitized_is_unknown(self):
        p,e=fixture(LOOP,code='VRFC 10-3365',message="index is not defined as a genvar [candidate.sv:3]")
        cards,t=self.retrieve(p,e)
        self.assertFalse(cards);self.assertEqual(t['empty_kind'],'not_needed')
        p,e=fixture(LOOP,code='VRFC 10-3365',message='invalid generate index [candidate.sv:3]')
        self.assertEqual(decide(GENVAR,e,p)['decision_class'],'unknown')
    def test_primary_binding_and_versions(self):
        for changes in ({'version':'2027.1'},{'message':"syntax error near ',' [candidate.sv:1]"}):
            p,e=fixture(**changes);self.assertFalse(self.retrieve(p,e)[0])
        p,e=fixture();self.assertFalse(self.retrieve(replace(p,code_hash='0'*64),e)[0])
        items=e['check'].details['knowledge_diagnostics']['items'];items.insert(0,dict(items[0],code='VRFC 10-1280'))
        self.assertFalse(self.retrieve(p,e)[0])

    def test_same_line_in_other_file_is_not_current_source(self):
        p,e=fixture(message="syntax error near ',' [unrelated.sv:2]")
        self.assertEqual(decide(F24,e,p)['reason'],'diagnostic_source_file_mismatch')
        p,e=fixture();e['check'].details.pop('source_binding')
        self.assertEqual(decide(F24,e,p)['reason'],'source_file_binding_missing')


class Attribution(unittest.TestCase):
    def test_distinct_failure_classes(self):
        cases=[({'delivered':False,'scored_hash':'old','functional_pass':False},'not_delivered'),
               ({'delivered':True,'checker_accepted':False},'checker_rejected'),
               ({'delivered':True,'checker_accepted':True,'new_hash':'new','scored_hash':'old','functional_pass':False},'different_candidate_scored'),
               ({'delivered':True,'checker_accepted':True,'new_hash':'new','scored_hash':'new','functional_pass':False},'new_draft_functional_failure'),
               ({'delivered':False,'environment_error':'compiler unavailable'},'environment_failure')]
        for inputs,expected in cases:self.assertEqual(classify_attempt(**inputs)['outcome'],expected)
    def test_quarantine_and_thinking_excluded(self):
        result=dict(job={'case':'nf-prob062-combinational'},complete_new_draft=True,checker_accepted=True,
                    draft_sha256='new',judge_input_sha256='new',judge={'stages':{'simulate':True}},
                    delivery={'phases':[{'thinking':True}]})
        self.assertFalse(classify_development_result(result)['eligible_for_effect_comparison'])
        result['job']['case']='public-authored'
        self.assertTrue(classify_development_result(result)['eligible_for_effect_comparison'])
        result['delivery']['phases'][0]['thinking']=False
        self.assertFalse(classify_development_result(result)['eligible_for_effect_comparison'])
    def test_old_score_and_unbound_legacy_score_not_promoted(self):
        result=dict(complete_new_draft=False,selected_sha256='old',judge={'stages':{'simulate':False}})
        self.assertEqual(classify_development_result(result)['outcome'],'not_delivered')
        result.update(complete_new_draft=True,checker_accepted=True,draft_sha256='new')
        self.assertEqual(classify_development_result(result)['outcome'],'new_draft_unscored')

    def test_nondelivery_stays_in_attempt_denominator(self):
        result=classify_attempt(delivered=False,scored_hash='old',functional_pass=False)
        self.assertFalse(result['eligible_for_effect_comparison'])
        self.assertTrue(result['eligible_for_attempt_success_rate'])
        self.assertFalse(result['attempt_success'])

    def test_experimental_profile_builds_and_small_budget_rejected(self):
        from agent.config import load_config
        from agent.knowledge.policy import validate_selection
        from agent.runtime.graph import build_graph
        import agent.nodes,agent.workflows
        config,_=load_config('dev/optimization-v4/thinking-staged.yaml',{})
        build_graph(NS(config=config,record=NS(run_id='offline',emit=lambda *a,**kw:None)))
        with self.assertRaises(ValueError):validate_selection({'delivery_mode':'thinking_staged','max_tokens':512})


if __name__=='__main__':unittest.main()
