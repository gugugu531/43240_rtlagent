"""Development adapter checks, not model or final acceptance measurements."""
import json
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from agent.knowledge.context import prepare
from agent.knowledge.assets import load_assets
from agent.knowledge.policy import select_skills
from agent.runtime.recorder import Recorder
from agent.knowledge.runtime import bundle
from admission import F24
from adapter import retrieve_development
from test_admission import fixture


class Integration(unittest.TestCase):
    def test_all_backends_and_modes(self):
        data,_=bundle()
        # This mock tests transport-independent assembly invariants only. It must
        # not be used as a semantic dense-retrieval score or a latency measurement.
        with tempfile.TemporaryDirectory() as root, patch('agent.knowledge.runtime.embed',return_value=data['documents'][0]['vector']):
            record=Recorder(root);self.addCleanup(record.close)
            ctx=NS(store={},record=record,llm=NS(tokenize=lambda m:len(json.dumps(m))//4),
                   config=NS(services=NS(model=NS(max_model_len=65536))))
            parent,e=fixture();messages=[{'role':'user','content':'Repair this candidate.'}]
            for strategy in ('exact','bm25','dense','hybrid'):
                for mode in ('off','shadow','on'):
                    with self.subTest(strategy=strategy,mode=mode),patch('agent.knowledge.runtime.retrieve_runtime',retrieve_development):
                        packed,trace=prepare(ctx,messages,parent,e,skill_ids=[],skill_phases=['repair'],rag=False,
                            max_tokens=16384,max_extra_tokens=2048,skill_mode='off',rag_mode=mode,
                            retrieval_options={'strategy':strategy})
                        self.assertEqual(packed==messages,mode!='on')
                        self.assertEqual(trace['sent'],[F24] if mode=='on' else [])
                        if mode!='off':
                            self.assertEqual(trace['retrieval']['admitted'],[F24])
                            self.assertEqual(trace['retrieval']['retrieved'][0]['lane'],'restricted_exact')

    def test_duplicate_and_missing_location_keep_messages_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            record=Recorder(root);self.addCleanup(record.close)
            ctx=NS(store={},record=record,llm=NS(tokenize=lambda m:len(json.dumps(m))//4),
                   config=NS(services=NS(model=NS(max_model_len=65536))))
            for message,feedback in [("syntax error near ','",''),
                                     ("syntax error near ',' [candidate.sv:2]",'Wrap the replication in an outer concatenation.')]:
                parent,e=fixture(message=message);messages=[{'role':'user','content':'Repair this candidate. '+feedback}]
                with patch('agent.knowledge.runtime.retrieve_runtime',retrieve_development):
                    packed,trace=prepare(ctx,messages,parent,e,skill_ids=[],skill_phases=['repair'],rag=False,
                        max_tokens=16384,max_extra_tokens=2048,rag_mode='on',raw_feedback=feedback)
                self.assertEqual(packed,messages);self.assertFalse(trace['sent'])

    def test_rejected_skills_not_promoted_and_candidates_never_auto(self):
        assets=load_assets(skills=True)
        for key in ('rtl-width-signed-arithmetic','rtl-combinational-completeness','rtl-fsm-state-output'):
            selected,rejected=select_skills(assets,[key],['repair'],automatic=True)
            self.assertFalse(selected);self.assertEqual(rejected[0]['reason'],'rejected_fixed_ab')
            skill,body=assets['skills'][key]
            candidate=skill.model_copy(update={'version':'2.0.0-dev.1','review_status':'frozen_candidate_not_default'})
            overlay={'skills':{key:(candidate,body)}}
            self.assertFalse(select_skills(overlay,[key],['repair'],automatic=True)[0])
            self.assertEqual(select_skills(overlay,[key],['repair'],automatic=False)[0],[key])


if __name__=='__main__':unittest.main()
