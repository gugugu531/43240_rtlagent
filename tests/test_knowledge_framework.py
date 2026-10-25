import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from agent.knowledge.context import prepare
from agent.knowledge.policy import modes, validate_selection
from agent.knowledge.runtime import bundle, retrieve_runtime, f24_matches, vector
from agent.rtl.candidate import CandidateFactory, CandidateStore
from agent.rtl.result import CheckResult, bind_result
from agent.runtime.recorder import Recorder
from agent.kit import State


class Framework(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.record = Recorder(self.tmp.name)
        self.addCleanup(self.record.close)
        self.calls = []
        self.ctx = NS(store={}, record=self.record,
                      llm=NS(tokenize=lambda m: len(json.dumps(m))//4),
                      config=NS(services=NS(model=NS(max_model_len=65536))))
        self.parent = CandidateFactory().create('module TopModule; assign y = {8{x}, x}; endmodule', source_stage='test', round=1)
        self.item = dict(code='VRFC 10-4982', tool='xvlog', version='2026.1', severity='error',
                         process_status='failed', message="syntax error near ','", command_index=0)
        self.messages = [{'role':'user','content':'Repair the current RTL using the diagnostic.'}]

    def evidence(self, **updates):
        item = dict(self.item, **updates)
        check = bind_result(CheckResult(status='failed', summary=item['message'], failure_kind='code',
                  details={'knowledge_diagnostics': {'complete':True,'items':[item]}}), self.parent, 'lint')
        return {'check':check,'execution_id':'execution-test'}

    def prepare(self, **kwargs):
        options = dict(skill_ids=[], skill_phases=['generate','repair'], rag=False,
                       max_tokens=1024,max_extra_tokens=2048)
        options.update(kwargs)
        return prepare(self.ctx, self.messages, self.parent, self.evidence(), **options)

    def test_off_is_identical(self):
        packed, trace = self.prepare(rag_mode='off')
        self.assertEqual(packed,self.messages)
        self.assertEqual(trace['sent'],[])

    def test_shadow_is_identical_with_positive_admission(self):
        packed, trace = self.prepare(rag_mode='shadow')
        self.assertEqual(packed,self.messages)
        self.assertEqual(len(trace['retrieval']['admitted']),1)
        self.assertEqual(trace['sent'],[])
        self.assertEqual(trace['pieces'][0]['status'],'shadow_only')

    def test_on_sends_only_admitted(self):
        packed, trace = self.prepare(rag_mode='on')
        self.assertNotEqual(packed,self.messages)
        self.assertEqual(trace['sent'],trace['retrieval']['admitted'])

    def test_no_budget(self):
        packed, trace = self.prepare(rag_mode='on',max_extra_tokens=0)
        self.assertEqual(packed,self.messages)
        self.assertEqual(trace['pieces'][0]['status'],'knowledge_budget')

    def test_unknown_version(self):
        cards, trace = retrieve_runtime(self.evidence(version='2027.1'),self.parent,{},self.messages)
        self.assertFalse(cards)
        self.assertEqual(trace['reason'],'unknown_version_or_nonfailure')

    def test_stale_candidate(self):
        other = CandidateFactory().create('other',source_stage='test',round=1)
        cards, trace = retrieve_runtime(self.evidence(),other,{},self.messages)
        self.assertFalse(cards)
        self.assertEqual(trace['reason'],'ineligible_or_stale_check')

    def test_correct_empty_mechanical(self):
        cards, trace = retrieve_runtime(self.evidence(code='VRFC 10-1280',message='procedural assignment to a non-register'),self.parent,{},self.messages)
        self.assertFalse(cards)
        self.assertEqual(trace['reason'],'correct_empty')
        self.assertTrue(all(x['reason']=='model_not_needed' for x in trace['rejected']))

    def test_duplicate_knowledge(self):
        cards, trace = retrieve_runtime(self.evidence(),self.parent,{},[{'content':'Use {{N{expr}}, slice}'}])
        self.assertFalse(cards)
        self.assertIn('knowledge_already_present',[x['reason'] for x in trace['rejected']])

    def test_secondary_cannot_trigger(self):
        e = self.evidence(code='VRFC 10-1280')
        e['check'].details['knowledge_diagnostics']['items'].append(self.item)
        cards, trace = retrieve_runtime(e,self.parent,{},self.messages)
        self.assertFalse(cards)

    def test_automatic_rejected_skill_skips(self):
        packed, trace = self.prepare(skill_ids=['rtl-fsm-state-output'],automatic=True,skill_mode='on')
        self.assertEqual(packed,self.messages)
        self.assertTrue(trace['skill_rejected'])
        self.assertEqual(trace['skill_rejected'][0]['reason'],'rejected_fixed_ab')

    def test_explicit_invalid_skill_preflight(self):
        with self.assertRaises(ValueError):
            validate_selection({'skill_ids':['rtl-fsm-state-output']})

    def test_skill_shadow(self):
        packed, trace = self.prepare(skill_ids=['rtl-sequential-state-update'],skill_mode='shadow')
        self.assertEqual(packed,self.messages)
        self.assertEqual(trace['pieces'][0]['status'],'shadow_only')

    def test_dense_unavailable_declared_empty(self):
        cards, trace = retrieve_runtime(self.evidence(),self.parent,{'strategy':'dense'},self.messages)
        self.assertFalse(cards)
        self.assertEqual(trace['effective_strategy'],'empty')
        self.assertIn('embedding_ms',trace)

    def test_dense_unavailable_declared_exact(self):
        cards, trace = retrieve_runtime(self.evidence(),self.parent,{'strategy':'dense','fallback':'exact'},self.messages)
        self.assertEqual(len(cards),1)
        self.assertEqual(trace['effective_strategy'],'exact')

    def test_all_backends_uniform(self):
        data,_ = bundle()
        with patch('agent.knowledge.runtime.embed',return_value=data['documents'][0]['vector']):
            for strategy in ('exact','bm25','dense','hybrid'):
                with self.subTest(strategy=strategy):
                    cards, trace = retrieve_runtime(self.evidence(),self.parent,{'strategy':strategy},self.messages)
                    self.assertEqual(len(cards),1)
                    self.assertTrue(trace['retrieved'])
                    self.assertEqual(trace['effective_strategy'],strategy)

    def test_f24_comments_not_evidence(self):
        parent = NS(code='// {8{x}, x}\nmodule TopModule; endmodule')
        self.assertFalse(f24_matches(parent,self.item,'lint'))

    def test_f24_valid_replication_not_hit(self):
        for code in ('{8{x}}','{{8{x}},x}'):
            self.assertFalse(f24_matches(NS(code=code),self.item,'lint'))

    def test_vector_validation(self):
        for value in ([0.0]*1024,[float('nan')]*1024,[1.0]):
            with self.assertRaises(ValueError):
                vector(value,1024)

    def test_no_delivery_retains_old_candidate(self):
        from agent.nodes.extract import extract
        store = CandidateStore(self.record,self.tmp.name)
        old = store.create('module TopModule; endmodule')
        store.select(old.id,'baseline')
        self.ctx.candidates,self.ctx.task = store,NS(top='TopModule')
        self.ctx.store['call-test'] = NS(content='I cannot provide the module.',call_id='call-test',finish_reason='length')
        state = extract(self.ctx,State({'reply_id':'call-test','round':2,'target_id':old.id}))
        self.assertFalse(state['has_candidate'])
        self.assertEqual(store.selected_id,old.id)
        self.assertEqual(state['target_id'],old.id)

    def test_defaults_and_conflicts(self):
        from agent.workflows.adaptive_verify import AdaptiveParameters
        self.assertFalse(AdaptiveParameters().rag)
        self.assertEqual(modes(),('off','off'))
        with self.assertRaises(ValueError):
            modes(rag=True,rag_mode='shadow')

    def test_release_is_label_free(self):
        data,_ = bundle()
        self.assertNotIn('queries',data)
        self.assertEqual(len(data['documents']),32)
        self.assertNotIn('oracle_family_id',json.dumps(data))

    def test_optional_asset_failure_does_not_block(self):
        with patch('agent.knowledge.context.load_assets',side_effect=ValueError('bad hash')):
            packed, trace = self.prepare(skill_ids=['rtl-sequential-state-update'])
        self.assertEqual(packed,self.messages)
        self.assertEqual(trace['reason'],'optional_knowledge_failure')

    def test_checkpoint_filter_binding(self):
        data,digest = bundle()
        data = dict(data, checkpoints=[{'card_id':'repair-local-syntax',
                 'card_version':next(r for r in data['rules'] if r['card_id']=='repair-local-syntax')['card_version'],
                 'card_sha256':next(r for r in data['rules'] if r['card_id']=='repair-local-syntax')['card_sha256'],
                 'candidate_sha256':self.parent.code_hash,'feedback_sha256':__import__('hashlib').sha256(b'feedback').hexdigest()}])
        with patch('agent.knowledge.runtime.bundle',return_value=(data,digest)), patch(
                'agent.knowledge.runtime.embed',return_value=data['documents'][0]['vector']):
            _, trace = retrieve_runtime(self.evidence(),self.parent,{'strategy':'dense','retrieve_k':32},self.messages,'feedback')
        self.assertIn('checkpoint_correct_empty',[x['reason'] for x in trace['rejected']])

    def test_all_packaged_configs_build(self):
        import agent.nodes
        import agent.workflows
        from agent.config import load_config
        from agent.runtime.graph import build_graph
        for path in Path('config').glob('*.yaml'):
            with self.subTest(config=path.name):
                config,_ = load_config(path,{})
                build_graph(NS(config=config,record=self.record))

    def test_adaptive_rejected_skills_still_deliver(self):
        from agent.nodes.adaptive import _request
        from agent.workflows.adaptive_verify import AdaptiveParameters
        from agent.runtime.allowance import CompletionLedger
        from agent.runtime.budget import Budget
        from agent.llm.client import Client
        from agent.config import ModelConfig
        from baseline import load_generation
        for identity in ('rtl-width-signed-arithmetic','rtl-combinational-completeness','rtl-fsm-state-output'):
            budget = Budget(900,20,record=self.record)
            self.ctx.llm = Client(ModelConfig(backend='mock'),budget,self.record,load_generation())
            self.ctx.store['adaptive'] = {'attempted':set(),'settings':AdaptiveParameters().model_dump(mode='json'),
                 'ledger':CompletionLedger(budget,self.record,max_calls=7,max_output_tokens=10000),
                 'routing':NS(skill_ids=[identity]),'request_outcomes':{}}
            reply = _request(self.ctx,'draft',self.messages,limits={'timeout_s':30.0,'max_tokens':1024})
            self.assertIsNotNone(reply)
            self.assertEqual(self.ctx.llm.requests[-1]['messages'],self.messages)
            self.ctx.llm.close()


class GraphAcceptance(unittest.TestCase):
    def run_case(self, mode, *, no_delivery=False, skill_ids=None, workflow='repair_loop'):
        import agent.nodes
        import agent.workflows
        from agent.config import load_config
        from agent.runtime.context import Ctx
        from agent.runtime.budget import Budget
        from agent.runtime.graph import run_graph, build_graph
        from agent.rtl.task import TaskSpec
        from agent.llm.client import Client
        from agent.llm.mock import make_transport
        from agent.prompts import TemplateRenderer
        from baseline import load_generation
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder(directory)
            config,_ = load_config(Path('config') / f'{workflow}.yaml', {})
            from agent.config import Component
            config.nodes['generate'] = Component(use='rtl_generate', params={
                'rag_mode':mode,'skill_ids':skill_ids or []})
            budget = Budget(900,20,record=record)
            response = 'No complete module delivered.' if no_delivery else 'module TopModule; wire x; wire [8:0] y; assign y = {{8{x}},x}; endmodule'
            llm = Client(config.services.model,budget,record,load_generation(),transport=make_transport(responses={
                'generate':['module TopModule; wire x; wire [8:0] y; assign y = {8{x},x}; endmodule'],
                'repair':[response]}))
            ctx = Ctx(task=TaskSpec.from_text('synthetic','Implement module TopModule(); endmodule'),
                      budget=budget,llm=llm,record=record,processes=None,
                      candidates=CandidateStore(record,directory),prompts=TemplateRenderer(),config=config)
            def call(stage, *, candidate_id):
                candidate = ctx.candidates.get(candidate_id)
                failed = stage=='lint' and candidate.round==1
                item=dict(code='VRFC 10-4982',tool='xvlog',version='2026.1',severity='error',
                          process_status='failed',message="syntax error near ','",command_index=0)
                check = bind_result(CheckResult(status='failed' if failed else 'passed',summary='synthetic check',
                    blocking=failed, failure_kind='code' if failed else 'unknown',
                    details={'knowledge_diagnostics':{'complete':True,'items':[item] if failed else []}}),candidate,stage)
                record.emit(stage,'result',status=check.status,candidate_id=candidate.id)
                return check
            ctx.call = call
            try:
                if skill_ids:
                    with self.assertRaises(ValueError):
                        build_graph(ctx)
                    self.assertFalse(llm.requests)
                    return
                state = run_graph(ctx)
                from agent.knowledge.outcome import summarize
                outcome = summarize(Path(directory)/'trace.jsonl',Path(directory)/'solution.v')
                requests = [r['messages'] for r in llm.requests]
                self.assertEqual(len(requests),2)
                self.assertTrue(outcome['solution_matches_selection'])
                self.assertIsNone(outcome['external_score'])
                return requests, outcome, state
            finally:
                llm.close()
                record.close()

    def test_full_graph_shadow_messages_match_off(self):
        off,_,_ = self.run_case('off')
        shadow,outcome,_ = self.run_case('shadow')
        # Candidate/check IDs are deterministic, execution IDs never enter prompts.
        self.assertEqual(off,shadow)
        self.assertTrue(outcome['assemblies'][1]['retrieval']['admitted'])
        self.assertFalse(outcome['assemblies'][1]['sent'])

    def test_full_graph_on_sends_card(self):
        requests,outcome,_ = self.run_case('on')
        self.assertIn('[Knowledge Card',requests[1][-1]['content'])
        self.assertTrue(outcome['selected_latest_complete'])

    def test_full_graph_no_delivery_scores_no_new_draft(self):
        _,outcome,_ = self.run_case('on',no_delivery=True)
        self.assertEqual(outcome['selected_candidate_id'],'c001')
        self.assertFalse(outcome['deliveries'][-1]['complete_new_draft'])

    def test_full_graph_explicit_rejected_fails_before_request(self):
        self.run_case('off',skill_ids=['rtl-fsm-state-output'])

    def test_cli_writes_joined_outcome(self):
        from agent.main import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / 'input'
            task.mkdir()
            (task/'prompt.txt').write_text('Implement module TopModule(); endmodule')
            configuration = root/'config.yaml'
            configuration.write_text('workflow: repair_loop\nparams: {max_rounds: 1}\nnodes:\n  check: {use: rtl_checks, params: {stages: [interface]}}\nservices:\n  model: {backend: mock}\nruntime:\n  recording: {level: full}\n')
            output=root/'output'
            main(['--input',str(task),'--output',str(output),'--config',str(configuration)])
            outcomes=list((output/'records').glob('*/framework-outcome.json'))
            self.assertEqual(len(outcomes),1)
            data=json.loads(outcomes[0].read_text())
            self.assertTrue(data['solution_matches_selection'])
            self.assertIsNone(data['external_score'])


if __name__ == '__main__':
    unittest.main()
