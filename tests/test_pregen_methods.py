"""Production wiring for the second restricted pre-generation batch."""
import json
from pathlib import Path
import unittest

from agent.knowledge.pregen import PREDICATES, decide
from agent.knowledge.pregen_methods import PREGEN_METHODS
from agent.knowledge.research import load_bundle


ROOT = Path(__file__).resolve().parents[1]


class PregenMethods(unittest.TestCase):
    def setUp(self):
        data = load_bundle()
        self.cards = {card['card_id']: card for card in data['cards']}
        self.tasks = {row['case_id']: row for row in json.loads(
            (ROOT / 'dev/optimization-v51/tasks.json').read_text())['tasks']}
        self.batch = json.loads((ROOT / 'dev/optimization-v54/batch.json').read_text())['cards']

    def test_all_ten_reviewed_methods_are_restricted_and_admit_the_public_fixture(self):
        self.assertEqual({row['card_id'] for row in self.batch}, set(PREGEN_METHODS))
        self.assertTrue(set(PREGEN_METHODS) <= set(PREDICATES))
        for row in self.batch:
            with self.subTest(card=row['card_id']):
                card = self.cards[row['card_id']]
                task = self.tasks[row['route_case_id']]
                self.assertEqual(card['activation_state'], 'restricted')
                self.assertTrue(card['injection_eligible'])
                self.assertEqual(card['injection_stages'], ['pre_generation'])
                self.assertIn('pre_generation', card['phases'])
                decision = decide(card, task['prompt'], task['interface'])
                self.assertTrue(decision['admit'], decision)
                self.assertEqual(decision['decision_class'], 'eligible')

    def test_incomplete_or_explicitly_inapplicable_contracts_fail_closed(self):
        for card_id in PREGEN_METHODS:
            with self.subTest(card=card_id):
                decision = decide(self.cards[card_id], 'Implement the requested RTL block.', '')
                self.assertFalse(decision['admit'])
                self.assertEqual(decision['decision_class'], 'unknown')
        examples = {
            'v8-lfsr-feedback-seed': 'Use inverted XOR complemented feedback and reset all zero.',
            'v8-ram-port-write-mode': 'Use synchronous RAM with write-first new data behavior.',
            'v9-public-division-remainder-invariant': 'Use signed division and allow divisor zero.',
        }
        gate_irrelevant = {
            'v8-result-backpressure-retention': 'Drop the pending result whenever ready is low.',
            'v8-serializer-snapshot': 'Read the live parallel input again for every serialized bit.',
            'v8-stack-boundary-guards': 'A push at full wraps and overwrites an entry.',
            'v9-public-carry-lookahead-composition': 'The two carry groups are independent.',
        }
        examples.update(gate_irrelevant)
        for card_id, prompt in examples.items():
            with self.subTest(card=card_id):
                decision = decide(self.cards[card_id], prompt, '')
                self.assertFalse(decision['admit'])
                self.assertEqual(decision['decision_class'], 'not_needed')


if __name__ == '__main__':
    unittest.main()
