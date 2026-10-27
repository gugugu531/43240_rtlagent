"""Language-only release and card/policy/index/configuration binding regressions."""
import copy
import json
from pathlib import Path
import re
import unittest
from agent.config import ROOT
from agent.domain.knowledge.assets import load_assets, card_text, sha256
from agent.domain.knowledge.context import NOTICE
from agent.domain.knowledge.policy import RetrievalOptions, validate_selection
from agent.domain.knowledge.release import read_lock, validate_release, fingerprint, policy_content
from agent.domain.knowledge.runtime import bundle
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.task import TaskSpec
from agent.domain.rtl.adaptive_repair import repair_request
from agent.domain.rtl.candidate import CandidateFactory

HAN = re.compile(r'[\u3400-\u9fff]')


class EnglishRelease(unittest.TestCase):
    def assert_english(self, value):
        self.assertIsNone(HAN.search(json.dumps(value, ensure_ascii=False)))

    def raw_release(self):
        raw=(ROOT/'knowledge/runtime-v1.json').read_bytes()
        return json.loads(raw),read_lock(),raw,(ROOT/'knowledge/cards.json').read_bytes()

    def test_all_prompt_templates_and_wrappers_english(self):
        template_paths = list((ROOT/'agent/context/prompts').glob('*.j2'))
        template_paths += list((ROOT/'agent/domain/rtl/instructions').glob('*.j2'))
        self.assertTrue(template_paths)
        for path in template_paths:
            self.assert_english(path.read_text())
        self.assert_english(NOTICE)
        self.assert_english((ROOT/'agent/domain/rtl/adaptive_repair.py').read_text())

    def test_rendered_generate_repair_and_adaptive_prompts_english(self):
        task=TaskSpec.from_text('synthetic','Implement a combinational identity function.',
                                'module TopModule(input a, output y); endmodule')
        parent=CandidateFactory().create('module TopModule(input a, output y); assign y=a; endmodule',
                                          source_stage='test',round=1)
        for feedback in ('','syntax error near a comma'):
            messages=TemplateRenderer().render('repair.j2',task=task,parent=parent,feedback=feedback,
                                                plan={'intent':'identity'})
            self.assert_english(messages)
        self.assert_english(repair_request(task,parent,{'kind':'syntax'}))

    def test_all_skill_bodies_english(self):
        assets=load_assets(skills=True)
        for skill,body in assets['skills'].values():
            self.assert_english(body)

    def test_six_legacy_cards_and_renderers_english(self):
        assets=load_assets(rag=True)
        self.assertEqual(len(assets['cards']),6)
        for card in assets['cards']:
            self.assertEqual(card.language,'en')
            self.assertEqual(card.version,'1.0.1-burr.en.1')
            self.assert_english(card.model_dump())
            self.assert_english(card_text(card))

    def test_32_cards_policy_and_index_bound(self):
        data,lock,raw,legacy=self.raw_release()
        validate_release(data,lock,raw,legacy)
        self.assert_english(data)
        self.assertEqual(len(data['cards']),32)
        self.assertTrue(all('source_card_version' in rule for rule in data['rules']))
        self.assertEqual(len(bundle()[0]['documents']),32)

    def test_stale_card_version_rejected_even_after_outer_rehash(self):
        data,lock,_,legacy=self.raw_release()
        data['rules'][0]['card_version']='stale-version'
        data['policy_sha256']=fingerprint(policy_content(data))
        lock['policy_sha256']=data['policy_sha256']
        raw=json.dumps(data).encode()
        lock['release_sha256']=sha256(raw)
        with self.assertRaisesRegex(ValueError,'card_policy_or_index_binding'):
            validate_release(data,lock,raw,legacy)

    def test_changed_card_body_rejected_even_after_outer_rehash(self):
        data,lock,_,legacy=self.raw_release()
        data['cards'][0]['guidance'][0]+=' Changed body.'
        raw=json.dumps(data).encode()
        lock['release_sha256']=sha256(raw)
        with self.assertRaisesRegex(ValueError,'card_policy_or_index_binding'):
            validate_release(data,lock,raw,legacy)

    def test_stale_legacy_hash_rejected(self):
        data,lock,raw,legacy=self.raw_release()
        with self.assertRaisesRegex(ValueError,'legacy_cards_sha256'):
            validate_release(data,lock,raw,legacy+b' ')

    def test_explicit_config_pin_mismatch_fails_preflight(self):
        for field in ('release_sha256','policy_sha256'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_selection({'rag_mode':'shadow','retrieval':{field:'0'*64}})

    def test_shadow_preset_matches_release_lock(self):
        from agent.config import load_config
        config,_=load_config(ROOT/'config/repair_rag_shadow.yaml',{})
        values=config.nodes['generate'].params
        self.assertEqual(values['rag_mode'],'shadow')
        options=RetrievalOptions.model_validate(values['retrieval'])
        lock=read_lock()
        self.assertEqual(options.release_sha256,lock['release_sha256'])
        self.assertEqual(options.policy_sha256,lock['policy_sha256'])
        validate_selection(values)


if __name__=='__main__':
    unittest.main()
