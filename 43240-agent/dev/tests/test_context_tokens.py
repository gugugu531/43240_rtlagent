"""Context compatibility and conservative accounting across real call lifecycles."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.core.model import BackendResponse, ModelRequest, ModelUsage
from agent.core.task import TaskSpec
from agent.core.tokens import TokenBudgetError, TokenCount, TokenLedger, TokenPolicy
from agent.prompts.builder import assemble_messages
from agent.prompts.context import ContextAssembler, ContextLimitError, ContextPiece
from agent.recording.recorder import RunRecorder
from agent.services.model import ModelService
from agent.nodes.generate import GenerateNode, GenerateInput
from agent.core.budget import Budget
from types import SimpleNamespace


class Counter:
    def count(self, messages, *, template_options=None):
        return TokenCount(sum(len(m['content']) for m in messages), 'exact')


class ContextTests(unittest.TestCase):
    def test_legacy_messages_and_resources_are_exactly_preserved(self):
        for style in ('direct', 'repair'):
            for interface in ('', 'module TopModule(input a, output q);'):
                for feedback in ('', 'ERROR: [VRFC 10-1280] broken'):
                    task = TaskSpec.from_text('test', 'Implement TopModule.', interface)
                    kwargs = dict(style=style, feedback=feedback, parent_code='module TopModule; endmodule')
                    old, resources = assemble_messages(task, **kwargs)
                    new = ContextAssembler().assemble(task, **kwargs)
                    self.assertEqual(new.messages, old)
                    self.assertEqual(new.resources, resources)

    def test_required_context_is_never_trimmed_to_fit(self):
        with self.assertRaises(ContextLimitError):
            ContextAssembler().assemble(TaskSpec.from_text('x', 'authoritative'),
                style='repair', counter=Counter(), context_limit=10, output_reserve=5)

    def test_optional_piece_is_whole_and_unknown_count_falls_back(self):
        task = TaskSpec.from_text('x', 'test')
        base = ContextAssembler().assemble(task, style='repair', counter=Counter(), output_reserve=5)
        pieces = (ContextPiece('one', 'guide'), ContextPiece('two', 'too large' * 20))
        result = ContextAssembler().assemble(task, style='repair', optional_pieces=pieces,
            counter=Counter(), context_limit=base.count.value + 12, output_reserve=5)
        self.assertEqual([p['status'] for p in result.pieces], ['included', 'context_limit'])
        self.assertTrue(result.messages[-1]['content'].endswith('\n\nguide'))
        unknown = ContextAssembler().assemble(task, style='repair', optional_pieces=pieces,
            context_limit=10000, output_reserve=5)
        self.assertEqual(unknown.messages, base.messages)
        self.assertEqual(unknown.pieces[0]['status'], 'tokens_unknown')

    def test_strict_unknown_and_duplicate_piece_are_rejected(self):
        task = TaskSpec.from_text('x', 'test')
        with self.assertRaises(ContextLimitError):
            ContextAssembler().assemble(task, style='repair', context_limit=10000, strict=True)
        with self.assertRaises(ValueError):
            ContextAssembler().assemble(task, style='repair', optional_pieces=(ContextPiece('x', 'a'), ContextPiece('x', 'b')))


class LedgerTests(unittest.TestCase):
    def test_counter_uses_only_options_actually_sent_by_request_profile(self):
        class RecordingCounter(Counter):
            def count(self, messages, *, template_options=None):
                self.options = template_options
                return super().count(messages, template_options=template_options)
        class Backend:
            def describe(self): return {'backend': 'test'}
            def complete(self, request):
                self.request = request
                return BackendResponse(0, 200, json.dumps({'choices': [{'message': {'content': 'ok'}}]}))
        for enabled in (True, False):
            for profile in ('baseline_rtl', 'default'):
                with self.subTest(enabled=enabled, profile=profile), tempfile.TemporaryDirectory() as temp, \
                     patch('baseline.load_generation', return_value={'chat_template_kwargs': {'enable_thinking': enabled}}):
                    recorder = RunRecorder(Path(temp)); counter = RecordingCounter(); backend = Backend()
                    service = ModelService(backend, recorder, token_counter=counter,
                                           template_options={'enable_thinking': enabled})
                    service.chat(ModelRequest([{'role': 'user', 'content': 'test'}], profile=profile))
                    payload = backend.request.payload('test')
                    expected = {'enable_thinking': enabled}
                    self.assertEqual(counter.options, expected)
                    self.assertEqual(payload.get('chat_template_kwargs', {}), expected)
                    recorder.close()

    def test_generation_reserves_remaining_output_instead_of_original_large_cap(self):
        class Backend:
            def describe(self): return {'backend': 'test'}
            def complete(self, request):
                self.request = request
                return BackendResponse(0, 200, json.dumps({'choices': [{'message': {'content': 'ok'}}]}))
        task = TaskSpec.from_text('x', 'test')
        required = ContextAssembler().assemble(task, style='repair', counter=Counter()).count.value
        for policy in (TokenPolicy(output_limit=2), TokenPolicy(total_limit=required + 2)):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as temp:
                recorder = RunRecorder(Path(temp)); backend = Backend()
                service = ModelService(backend, recorder, token_counter=Counter(), token_policy=policy,
                                       context_limit=required + 2, strict_context=True)
                ctx = SimpleNamespace(llm=service, budget=Budget(30,0), emit=lambda *args,**kwargs:None)
                GenerateNode(prompt_style='repair').run(ctx, GenerateInput(task))
                self.assertEqual(backend.request.max_tokens, 2)
                recorder.close()

    def test_observation_never_turns_unknown_into_zero(self):
        ledger = TokenLedger()
        ledger.start('m1', predicted_input=TokenCount(), output_cap=20)
        ledger.finish('m1', outcome='succeeded')
        snapshot = ledger.snapshot()
        self.assertIsNone(snapshot['tokens_out']['known_total'])
        self.assertIsNone(snapshot['charged_total'])
        self.assertEqual(snapshot['charged_output'], 20)
        self.assertEqual(ledger.allowance(TokenCount(), 20), 20)

    def test_total_budget_allocates_remaining_after_valid_usage(self):
        ledger = TokenLedger(TokenPolicy(total_limit=40))
        count = TokenCount(10, 'exact')
        self.assertEqual(ledger.allowance(count, 25), 25)
        ledger.start('m1', predicted_input=count, output_cap=25)
        ledger.finish('m1', usage=ModelUsage(10, 5), outcome='succeeded')
        self.assertEqual(ledger.allowance(count, 25), 15)

    def test_failed_or_unfinished_call_retains_output_reservation(self):
        for finish in (True, False):
            ledger = TokenLedger(TokenPolicy(output_limit=30))
            ledger.start('m1', predicted_input=TokenCount(), output_cap=20)
            if finish:
                ledger.finish('m1', outcome='failed')
            self.assertEqual(ledger.allowance(TokenCount(), 20), 10)
            self.assertEqual(ledger.snapshot()['unfinished'], int(not finish))

    def test_unknown_input_blocks_total_budget_and_mismatch_blocks_further_calls(self):
        ledger = TokenLedger(TokenPolicy(total_limit=100))
        with self.assertRaises(TokenBudgetError):
            ledger.allowance(TokenCount(), 10)
        ledger.start('m1', predicted_input=TokenCount(10, 'exact'), output_cap=10)
        ledger.finish('m1', usage=ModelUsage(11, 5), outcome='succeeded')
        with self.assertRaises(TokenBudgetError):
            ledger.allowance(TokenCount(10, 'exact'), 10)

    def test_call_identity_and_finish_cannot_be_duplicated(self):
        ledger = TokenLedger()
        ledger.start('m1', predicted_input=TokenCount(), output_cap=10)
        with self.assertRaises(ValueError):
            ledger.start('m1', predicted_input=TokenCount(), output_cap=10)
        ledger.finish('m1', outcome='failed')
        with self.assertRaises(ValueError):
            ledger.finish('m1', outcome='failed')
        for value in (True, 0, -1, 0.5):
            with self.assertRaises(ValueError):
                TokenPolicy(total_limit=value)

    def test_model_service_enforces_output_cap_and_records_missing_usage(self):
        class Backend:
            def describe(self): return {'backend': 'test'}
            def complete(self, request):
                self.request = request
                return BackendResponse(0, 200, json.dumps({'choices': [{'message': {'content': 'ok'}}]}))
        with tempfile.TemporaryDirectory() as temp:
            recorder = RunRecorder(Path(temp))
            backend = Backend()
            service = ModelService(backend, recorder, token_policy=TokenPolicy(output_limit=7))
            service.chat(ModelRequest([{'role': 'user', 'content': 'test'}], max_tokens=10))
            self.assertEqual(backend.request.max_tokens, 7)
            with self.assertRaises(TokenBudgetError):
                service.chat(ModelRequest([{'role': 'user', 'content': 'test'}], max_tokens=10))
            recorder.close()
            events = [json.loads(line) for line in (Path(temp) / 'trace.jsonl').read_text().splitlines()]
            self.assertEqual(sum(e.get('tool') == 'llm' and e.get('event') == 'started' for e in events), 1)
            self.assertTrue(any(e.get('event') == 'denied' for e in events))


class LocalTokenizerTests(unittest.TestCase):
    def test_local_template_special_tokens_and_thinking_are_counted(self):
        from tokenizers import Tokenizer, models, pre_tokenizers, AddedToken
        from agent.services.tokenizer import LocalTokenCounter
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'hello': 1}, unk_token='[UNK]'))
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            tokenizer.add_special_tokens([AddedToken('<s>', special=True), AddedToken('</s>', special=True)])
            tokenizer.save(str(root / 'tokenizer.json'))
            (root / 'tokenizer_config.json').write_text(json.dumps({'chat_template':
                "<s>{{ messages[0].content }}</s>{% if enable_thinking is defined and not enable_thinking %} no think{% endif %}"}))
            counter = LocalTokenCounter(root)
            messages = [{'role': 'user', 'content': 'hello'}]
            self.assertEqual(counter.count(messages).value, 3)
            self.assertEqual(counter.count(messages, template_options={'enable_thinking': False}).value, 5)
            (root / 'tokenizer_config.json').write_text(json.dumps({'chat_template':
                "{{ messages[0].content }} {{ mode }} {{ budget }} {{ ratio }}{% if flag %} yes{% endif %}"}))
            scalar_counter = LocalTokenCounter(root)
            count = scalar_counter.count(messages, template_options={'mode':'fast', 'budget':2, 'ratio':0.5, 'flag':True})
            self.assertEqual(count.status, 'exact')
            self.assertEqual(count.value, len(tokenizer.encode('hello fast 2 0.5 yes', add_special_tokens=False).ids))
            self.assertEqual(scalar_counter.count(messages, template_options={'nested':{}}).status, 'unavailable')
            self.assertEqual(counter.count([{'role': 'user', 'content': []}]).status, 'unavailable')
            with self.assertRaises(ValueError):
                LocalTokenCounter(root, expected_tokenizer_sha256='0' * 64)
            counter.mark_mismatch()
            self.assertEqual(counter.count(messages).status, 'mismatch')
