"""Model evidence tests use fake HTTP responses, never a paid service."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.config import ModelConfig, ModelConfigError
from agent.core.model import ModelRequest, ModelCallError
from agent.services.model import ModelService, HttpBackend, MockBackend
from agent.recording.recorder import RunRecorder, RecordingConfig, RecordingError
from agent.nodes.extraction import extract_result


def config():
    return ModelConfig(backend='openai', model='test-model', base_url='http://localhost:8000/v1',
                       api_key='explicit-test-secret')


def body(content='module TopModule; endmodule'):
    return dict(id='request-id', model='served-model',
                choices=[dict(message=dict(content=content, reasoning_content='reasoning evidence'),
                              finish_reason='stop')], provider_extra=dict(example=True))


class ModelTests(unittest.TestCase):
    def invoke(self, recorder, *, text=None, status=200, error=None, request=None):
        service = ModelService(HttpBackend(config()), recorder)
        response = SimpleNamespace(status_code=status, text=text if text is not None else json.dumps(body()))
        with patch('requests.post', return_value=response, side_effect=error) as post:
            reply = service.chat(request or ModelRequest([dict(role='user', content='task')]))
        return reply, post

    def events(self, temp):
        return [json.loads(line) for line in Path(temp, 'trace.jsonl').read_text().splitlines()]

    def test_full_response_and_request_are_preserved(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            request = ModelRequest([dict(role='user', content='explicit-test-secret')],
                                   max_tokens=101, temperature=0.7, timeout_s=2, purpose='repair')
            reply, post = self.invoke(recorder, request=request)
            recorder.close()
            call = recorder.run_dir / 'calls/m001'
            parsed = json.loads((call / 'response.json').read_text())
            self.assertEqual(parsed, body())
            self.assertIn('reasoning evidence', (call / 'response.txt').read_text())
            self.assertEqual(reply.request_id, 'request-id')
            self.assertIsNone(reply.usage.tokens_in)
            self.assertIsNone(reply.usage.tokens_out)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 101)
            self.assertEqual(post.call_args.kwargs['timeout'], 2)
            self.assertEqual(reply.response_artifact.path, 'calls/m001/response.txt')
            self.assertEqual(request.messages[0]['content'], 'explicit-test-secret')
            self.assertNotIn('explicit-test-secret', (call / 'request.json').read_text())
            self.assertEqual([e['event'] for e in self.events(temp) if e['tool']=='llm'], ['started', 'succeeded'])

    def test_http_json_and_shape_errors_keep_evidence(self):
        for status, text, kind in [(429, '{"diagnostic":"busy"}', 'http'),
                                   (503, '<html>unavailable</html>', 'http'),
                                   (200, 'not-json', 'json'), (200, '{"extra":1}', 'response'),
                                   (200, 'null', 'response')]:
            with self.subTest(kind=kind, status=status, text=text), TemporaryDirectory() as temp:
                recorder = RunRecorder(temp)
                with self.assertRaises(ModelCallError) as caught:
                    self.invoke(recorder, text=text, status=status)
                recorder.close()
                error = caught.exception
                self.assertEqual(error.kind, kind)
                self.assertEqual(error.call_id, 'm001')
                self.assertEqual((recorder.run_dir / error.evidence.path).read_text(), text)
                ended = [e for e in self.events(temp) if e['tool']=='llm' and e['event']=='failed']
                self.assertEqual(len(ended), 1)
                self.assertFalse((recorder.run_dir/'calls/m001/content.txt').exists())

    def test_timeout_connection_have_no_fabricated_response(self):
        for exception, kind in [(requests.Timeout('secret'), 'timeout'),
                                (requests.ConnectionError('secret'), 'connection')]:
            with TemporaryDirectory() as temp:
                recorder = RunRecorder(temp)
                with self.assertRaises(ModelCallError) as caught:
                    self.invoke(recorder, error=exception)
                self.assertEqual(caught.exception.kind, kind)
                self.assertTrue(caught.exception.retryable)
                self.assertIsNone(caught.exception.evidence)
                self.assertFalse((recorder.run_dir / 'calls/m001/response.txt').exists())
                recorder.close()

    def test_mock_is_explicit_and_not_http(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            reply = ModelService(MockBackend(), recorder).chat(ModelRequest([
                dict(role='user', content='module TopModule(input a, output q);')]))
            recorder.close()
            self.assertIn('MOCK BACKEND', reply.content)
            self.assertIsNone(reply.response_artifact)
            self.assertFalse((recorder.run_dir/'calls/m001/response.txt').exists())
            self.assertIsNone(reply.usage.tokens_in)

    def test_basic_mode_has_trace_but_no_raw_artifacts(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp, RecordingConfig('basic'))
            self.invoke(recorder)
            recorder.close()
            self.assertFalse(recorder.run_dir.exists())
            self.assertEqual(len([e for e in self.events(temp) if e['tool']=='llm']), 2)

    def test_optional_recording_failure_preserves_reply_and_original_error(self):
        for fail in [False, True]:
            with TemporaryDirectory() as temp:
                blocked = Path(temp, 'blocked'); blocked.write_text('file, not directory')
                recorder = RunRecorder(temp, RecordingConfig(root=blocked))
                with self.assertWarns(RuntimeWarning):
                    if fail:
                        with self.assertRaises(ModelCallError) as caught:
                            self.invoke(recorder, text='bad JSON')
                        self.assertEqual(caught.exception.kind, 'json')
                    else:
                        reply, _ = self.invoke(recorder)
                        self.assertEqual(reply.content, 'module TopModule; endmodule')
                        self.assertIsNone(reply.response_artifact)
                    recorder.close()
                self.assertTrue(any(e['event']=='warning' for e in self.events(temp)))

    def test_required_trace_write_failure_is_infrastructure_error(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            with patch.object(recorder._trace, 'write', side_effect=OSError('disk')):
                with self.assertRaises(RecordingError):
                    self.invoke(recorder)
            recorder.close()

    def test_unfinished_call_remains_started(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            recorder.begin_call(ModelRequest([]), dict(backend='mock'))
            recorder.close()
            manifest = json.loads((recorder.run_dir/'run.json').read_text())
            self.assertEqual(manifest['calls']['m001']['status'], 'started')
            self.assertFalse(any(e['event']=='succeeded' for e in self.events(temp)))

    def test_extraction_records_truncation_and_ambiguity_with_call_id(self):
        for content, status in [('```verilog\nmodule TopModule;\n```', 'incomplete'),
                                ('```verilog\nmodule TopModule; endmodule\n```\n'
                                 '```verilog\nmodule TopModule; wire b; endmodule\n```', 'ambiguous')]:
            with TemporaryDirectory() as temp:
                recorder = RunRecorder(temp)
                reply, _ = self.invoke(recorder, text=json.dumps(body(content)))
                extracted = extract_result(reply.content, 'TopModule')
                recorder.record_extraction(reply.call_id, extracted, 'c001' if extracted.code else None)
                recorder.close()
                recorded = json.loads((recorder.run_dir/'calls/m001/extraction.json').read_text())
                self.assertEqual(recorded['status'], status)
                self.assertEqual(recorded['call_id'], 'm001')
                self.assertEqual(recorded['candidate_id'], 'c001' if extracted.code else None)

    def test_unknown_usage_and_null_content(self):
        data = body(None); data['usage'] = dict(prompt_tokens=0, completion_tokens='bad')
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            reply, _ = self.invoke(recorder, text=json.dumps(data))
            recorder.close()
            self.assertEqual(reply.content, '')
            self.assertEqual(reply.usage.tokens_in, 0)
            self.assertIsNone(reply.usage.tokens_out)

    def test_configuration_validation(self):
        self.assertEqual(ModelConfig.from_env({}).backend, 'mock')
        for env in [dict(LLM_BACKEND='unknown'), dict(LLM_BACKEND='openai'),
                    dict(LLM_TIMEOUT_S='nan'), dict(LLM_TIMEOUT_S='0')]:
            with self.assertRaises(ModelConfigError):
                ModelConfig.from_env(env)
        for values in [dict(timeout_s=0), dict(max_tokens=0), dict(temperature=-1)]:
            with self.assertRaises(ModelCallError):
                ModelRequest([], **values)


class RecordingIsolationTests(unittest.TestCase):
    def test_multiple_calls_and_runs_are_distinct(self):
        with TemporaryDirectory() as temp:
            root = Path(temp, 'records')
            run_dirs = []
            for number in range(2):
                recorder = RunRecorder(Path(temp, f'output{number}'), RecordingConfig(root=root))
                service = ModelService(MockBackend(), recorder)
                request = ModelRequest([dict(role='user', content='module TopModule();')])
                self.assertEqual([service.chat(request).call_id for _ in range(2)], ['m001', 'm002'])
                recorder.close()
                run_dirs.append(recorder.run_dir)
            self.assertNotEqual(*run_dirs)
            self.assertTrue(all((d/'calls/m002/content.txt').exists() for d in run_dirs))

    def test_request_nested_values_are_immutable_and_recording_does_not_change_reply(self):
        messages = [dict(role='user', content=[dict(text='original')])]
        request = ModelRequest(messages)
        messages[0]['content'][0]['text'] = 'changed'
        self.assertEqual(request.public_dict()['messages'][0]['content'][0]['text'], 'original')
        with self.assertRaises(TypeError):
            request.messages[0]['content'][0]['text'] = 'changed'
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp, secrets=['small'])
            content = 'small secret; https://user:password@example.com/path?token=value'
            response = SimpleNamespace(status_code=200, text=json.dumps(body(content)))
            with patch('requests.post', return_value=response):
                reply = ModelService(HttpBackend(config()), recorder).chat(ModelRequest([]))
            recorder.close()
            self.assertEqual(reply.content, content)
            raw = '\n'.join(p.read_text() for p in recorder.run_dir.rglob('*') if p.is_file())
            self.assertNotIn('small', raw)
            self.assertNotIn('user:password', raw)
            self.assertNotIn('token=value', raw)

    def test_trace_failure_after_response_is_not_reclassified_as_model_error(self):
        with TemporaryDirectory() as temp:
            recorder = RunRecorder(temp)
            real_write = recorder.write_event
            def fail_on_end(tool, event='result', **fields):
                if tool == 'llm' and event == 'succeeded':
                    raise RecordingError('trace lost')
                return real_write(tool, event, **fields)
            with patch.object(recorder, 'write_event', side_effect=fail_on_end):
                with self.assertRaises(RecordingError):
                    ModelService(MockBackend(), recorder).chat(ModelRequest([]))
            recorder.close()


if __name__ == "__main__":
    unittest.main()
