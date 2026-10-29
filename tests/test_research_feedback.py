"""Packaged feedback-card invariants and embedding service identity."""

import unittest
from unittest.mock import patch
import httpx

from agent.domain.knowledge.research import load_bundle
from agent.domain.knowledge.runtime import embed
from agent.domain.knowledge.policy import RetrievalOptions


class ResearchFeedback(unittest.TestCase):
    def setUp(self):self.data=load_bundle()

    def test_every_allowed_card_has_both_feedback_phases_and_example(self):
        cards=[c for c in self.data['cards'] if c['card_id'].startswith(('v8-','v9-'))]
        self.assertEqual(len(cards),97)
        for c in cards:
            self.assertTrue(c['safe_example']);self.assertIn('post_diagnostic',c['phases'])
            self.assertIn('post_functional_feedback',c['phases']);self.assertFalse(c['feedback_contract']['default_injection'])

    def test_model_name_echo_cannot_bypass_advertised_identity(self):
        data=self.data|{'model':self.data['model']|{'runtime_alias':'requested-but-not-loaded'}}
        original=httpx.Client;methods=[]
        def handler(request):
            methods.append(request.method)
            return httpx.Response(200,json={'data':[{'id':self.data['model']['runtime_alias']}]})
        def client(**kwargs):return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('agent.domain.knowledge.runtime.httpx.Client',side_effect=client),self.assertRaisesRegex(ValueError,'advertised_model_mismatch'):
            embed(data,'public query',RetrievalOptions(strategy='dense',embedding_url='http://127.0.0.1:8765'))
        self.assertEqual(methods,['GET'])


if __name__=='__main__':unittest.main()
