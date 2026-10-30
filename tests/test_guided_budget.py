"""Clipped model requests preserve the tool reserve and request accounting."""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from agent.runtime.allowance import CompletionLedger
from agent.orchestration.nodes import guided


class GuidedBudgetTests(unittest.TestCase):
    def context(self, remaining):
        events, artifacts, sent = [], {}, []
        record = SimpleNamespace(
            emit=lambda *args, **kwargs: events.append((args, kwargs)),
            write_json=lambda name, value: artifacts.update({name: value}),
        )
        ledger = CompletionLedger(SimpleNamespace(remaining=lambda: remaining), record,
                                  max_calls=1, max_output_tokens=100)

        class Model:
            @contextmanager
            def permitted(self, permit):
                self.permit = permit
                permit._begin()
                try:
                    yield
                finally:
                    permit._finish()

            def chat(self, messages, **kwargs):
                sent.append(kwargs)
                self.permit._sent("m1", kwargs["max_tokens"])
                self.permit._response({"usage": {"prompt_tokens": 3, "completion_tokens": 7}})
                return SimpleNamespace(call_id="m1", finish_reason="stop")

        data = {"ledger": ledger, "attempted": set(), "request_outcomes": {},
                "settings": {"minimum_request_s": 20, "temperature": 0, "top_p": 1}}
        ctx = SimpleNamespace(store={"guided": data}, record=record, llm=Model())
        return ctx, ledger, sent, events

    def test_remaining_time_clips_request_and_keeps_followup(self):
        ctx, ledger, sent, events = self.context(360)
        reply = guided._request(ctx, "checker", [], {"max_tokens": 100, "timeout_s": 300},
                                followup_s=120)
        self.assertEqual(reply.call_id, "m1")
        self.assertEqual(sent[0]["timeout_s"], 240)
        permit = ledger.snapshot()["permits"][0]
        self.assertEqual(permit["followup_s"], 120)
        self.assertEqual(permit["timeout_s"], 240)
        self.assertEqual(ledger.snapshot()["known_output_tokens"], 7)
        reserved = next(fields for (_, event), fields in events if event == "reserved")
        self.assertEqual(reserved["requested_timeout_s"], 300)
        self.assertEqual(reserved["min_timeout_s"], 20)
        self.assertIsNone(ledger.reserve("second", 10, 1, optional=False))
        self.assertEqual(ledger.last_denial, "call_limit")

    def test_below_minimum_sends_nothing(self):
        ctx, ledger, sent, _ = self.context(139)
        self.assertIsNone(guided._request(ctx, "checker", [],
                                         {"max_tokens": 100, "timeout_s": 300}, followup_s=120))
        self.assertEqual(sent, [])
        self.assertEqual(ledger.snapshot()["calls_sent"], 0)
        self.assertEqual(ctx.store["guided"]["request_outcomes"]["checker"],
                         {"status": "not_sent", "reason": "insufficient_followup_time"})

    def test_minimum_boundary_and_fractional_clipping(self):
        for remaining in (140, 360.0000001):
            with self.subTest(remaining=remaining):
                _, ledger, _, _ = self.context(remaining)
                permit = ledger.reserve("checker", 10, 300, followup_s=120,
                                        min_timeout_s=20)
                self.assertIsNotNone(permit)
                self.assertEqual(permit.timeout_s, remaining - 120)
                self.assertLessEqual(permit.remaining_s(), remaining - 120)

    def test_legacy_reservation_stays_strict(self):
        _, ledger, _, _ = self.context(360)
        self.assertIsNone(ledger.reserve("legacy", 10, 300, followup_s=120))
        self.assertEqual(ledger.last_denial, "insufficient_followup_time")

    def test_explicit_short_stage_limit_is_respected(self):
        ctx, _, sent, _ = self.context(125)
        self.assertIsNotNone(guided._request(ctx, "checker", [],
                                            {"max_tokens": 10, "timeout_s": 5}, followup_s=120))
        self.assertEqual(sent[0]["timeout_s"], 5)

    def test_invalid_minimum_is_rejected(self):
        for minimum in (0, -1, 301, float("inf"), float("nan")):
            with self.subTest(minimum=minimum):
                _, ledger, _, _ = self.context(900)
                with self.assertRaises(ValueError):
                    ledger.reserve("checker", 10, 300, min_timeout_s=minimum)
