"""External corpus contracts tested only with artificial data."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from agent.core.diagnostic import Diagnostic
from agent.core.configuration import ConfigDocument, ConfigError, resolve_config
from agent.services.knowledge import load_corpus, retrieve_repair_guides
from support import synthetic_corpus, write_synthetic_corpus


class KnowledgeTests(unittest.TestCase):
    def test_malformed_root_and_nested_structures_raise_value_error(self):
        bad = [[], None, True, 1, 'text', {}, {'schema_version': 1},
               dict(synthetic_corpus(), cards=[None]), dict(synthetic_corpus(), cards=[[]]),
               dict(synthetic_corpus(), sources={'test-source': None})]
        for key, value in [('id', []), ('validation_sha256', 123), ('title', None),
                           ('applies_when', ''), ('source_ids', [None]), ('codes', [{}])]:
            corpus = synthetic_corpus(); corpus['cards'][0][key] = value; bad.append(corpus)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'bad.json'
            for value in bad:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(ValueError): load_corpus(path)

    def test_external_path_resolves_from_yaml_and_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            data = dict(schema_version=1, services={'knowledge': {'corpus_path': 'local.json'}})
            cfg = resolve_config(ConfigDocument(base/'config.yaml', data), env={})
            self.assertEqual(cfg.values['services']['knowledge']['corpus_path'], str(base/'local.json'))
            cfg = resolve_config(ConfigDocument(None, {'schema_version': 1}), env={})
            self.assertIsNone(cfg.values['services']['knowledge']['corpus_path'])
            with self.assertRaises(ConfigError):
                resolve_config(ConfigDocument(None, dict(schema_version=1,
                    services={'knowledge': {'corpus_path': 123}})), env={})

    def test_loading_does_not_require_any_packaged_corpus(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = load_corpus(write_synthetic_corpus(temp))
            self.assertEqual(corpus['cards'][0]['id'], 'test-guide')
            path = Path(temp)/'bad.json'
            for field, value in [('tool_validation', 'draft'), ('message_contains_any', [''])]:
                changed = deepcopy(corpus); changed['cards'][0][field] = value
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError): load_corpus(path)

    def test_message_condition_requires_same_error_tool_version_and_severity(self):
        corpus = synthetic_corpus()
        corpus['cards'][0]['message_contains_any'] = ['specific failure']
        diag = Diagnostic('k1', 'c1', 'lint', 'failed', 'code', 'xvlog', '2026.1',
                          'VRFC 10-1280', 'ERROR', 'SPECIFIC FAILURE')
        def retrieve(diagnostics):
            return retrieve_repair_guides(corpus, codes=('VRFC 10-1280',), tool='xvlog',
                                          version='2026.1', diagnostics=diagnostics)
        self.assertTrue(retrieve([diag])['pieces'])
        for wrong in [replace(diag, code='VRFC 10-9336'), replace(diag, tool='xelab'),
                      replace(diag, version='2025.2'), replace(diag, severity='WARNING'),
                      replace(diag, message='unrelated failure')]:
            with self.subTest(wrong=wrong):
                result = retrieve([wrong])
                self.assertFalse(result['pieces'])
                self.assertEqual(result['reason'], 'diagnostic_message_mismatch')
        self.assertFalse(retrieve([])['pieces'])

    def test_card_limit_and_character_omissions_are_recorded(self):
        corpus = synthetic_corpus()
        for suffix in ('b', 'c'):
            card = deepcopy(corpus['cards'][0]); card['id'] += '-'+suffix
            corpus['cards'].append(card)
        result = retrieve_repair_guides(corpus, codes=('VRFC 10-1280',), tool='xvlog', version='2026.1')
        self.assertEqual(len(result['pieces']), 2)
        self.assertEqual(result['omitted'], ['test-guide-c'])
        result = retrieve_repair_guides(corpus, codes=('VRFC 10-1280',), tool='xvlog',
                                       version='2026.1', max_chars=1)
        self.assertFalse(result['pieces'])
        self.assertEqual(result['reason'], 'character_budget')
