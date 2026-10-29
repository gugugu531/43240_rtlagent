"""Production wiring for the third restricted pre-generation batch."""
import json
from pathlib import Path
import unittest

from agent.domain.knowledge.pregen import PREDICATES, decide
from agent.domain.knowledge.pregen_methods_v55 import PREGEN_METHODS_V55
from agent.domain.knowledge.research import load_bundle

ROOT = Path(__file__).resolve().parents[1]


class PregenMethodsV55(unittest.TestCase):
    def setUp(self):
        data = load_bundle()
        self.cards = {card['card_id']: card for card in data['cards']}
        self.tasks = {row['case_id']: row for row in json.loads(
            (ROOT / 'dev/optimization-v51/tasks.json').read_text())['tasks']}
        self.batch = json.loads((ROOT / 'dev/optimization-v55/batch.json').read_text())['cards']

    def test_all_ten_are_restricted_and_admit_current_public_fixture(self):
        self.assertEqual({row['card_id'] for row in self.batch}, set(PREGEN_METHODS_V55))
        self.assertTrue(set(PREGEN_METHODS_V55) <= set(PREDICATES))
        for row in self.batch:
            with self.subTest(card=row['card_id']):
                card = self.cards[row['card_id']]
                task = self.tasks[row['route_case_id']]
                self.assertEqual(card['activation_state'], 'restricted')
                self.assertTrue(card['injection_eligible'])
                self.assertEqual(card['injection_stages'], ['pre_generation'])
                decision = decide(card, task['prompt'], task['interface'])
                self.assertTrue(decision['admit'], decision)

    def test_all_ten_fail_closed_for_incomplete_contract(self):
        for card_id in PREGEN_METHODS_V55:
            with self.subTest(card=card_id):
                decision = decide(self.cards[card_id], 'Implement the required RTL block.', '')
                self.assertFalse(decision['admit'])
                self.assertEqual(decision['decision_class'], 'unknown')


if __name__ == '__main__':
    unittest.main()
