"""One model call, transport evidence first, protocol validation second."""
from __future__ import annotations
import json
import time
from dataclasses import replace
import math
from collections.abc import Mapping
from agent.core.config import ModelConfig
from agent.core.model import (BackendResponse, ModelBackend, ModelCallError, ModelReply,
                          ModelRequest, ModelUsage, ModelReasoning)
from agent.recording.recorder import RunRecorder, RecordingError
from agent.services.mock import mock_content


class MockBackend:
    def __init__(self, model='mock-model'):
        self.model = model

    def describe(self):
        return dict(backend='mock', model=self.model)

    def complete(self, request):
        start = time.monotonic()
        content = mock_content(request.messages)
        return BackendResponse(time.monotonic() - start, mock_content=content)


class HttpBackend:
    def __init__(self, config: ModelConfig):
        self.config = config

    def describe(self):
        return dict(backend='openai', model=self.config.model, base_url=self.config.base_url)

    def baseline_model(self, timeout_s):
        if self.config.baseline_model_name:
            return self.config.baseline_model_name, 'MODEL_NAME'
        import requests
        try:
            response = requests.get(self.config.base_url + '/models', timeout=timeout_s)
            response.raise_for_status()
            data = response.json().get('data', [])
            model = data[0]['id'] if data else None
            return (model, 'models') if model else ('default', 'fallback')
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, AttributeError):
            return 'default', 'fallback'

    def complete(self, request: ModelRequest):
        import requests
        headers = {'Content-Type': 'application/json'}
        if self.config.api_key and request.profile != 'baseline_rtl':
            headers['Authorization'] = f'Bearer {self.config.api_key}'
        start = time.monotonic()
        try:
            response = requests.post(
                self.config.base_url + '/chat/completions', headers=headers,
                json=request.payload(self.config.model),
                timeout=request.timeout_s)
        except requests.Timeout as exc:
            raise ModelCallError('model request timed out', kind='timeout', retryable=True,
                                 elapsed_s=time.monotonic() - start) from exc
        except requests.RequestException as exc:
            # Exception strings may include credentials or HTTP headers.
            raise ModelCallError('model transport failed', kind='connection', retryable=True,
                                 elapsed_s=time.monotonic() - start) from exc
        return BackendResponse(time.monotonic() - start, response.status_code, response.text)


def make_backend(config: ModelConfig) -> ModelBackend:
    return MockBackend(config.model) if config.backend == 'mock' else HttpBackend(config)


def _token_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_reply(body, call_id, response, artifact):
    def invalid(message):
        raise ModelCallError(message, kind='response', elapsed_s=response.elapsed_s)
    if not isinstance(body, Mapping):
        invalid('model response must be a JSON object')
    choices = body.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        invalid('model response has no valid choice')
    choice = choices[0]
    message = choice.get('message')
    if not isinstance(message, Mapping):
        invalid('model choice has no message object')
    content = message.get('content')
    if content is not None and not isinstance(content, str):
        invalid('model content must be a string or null')
    finish = choice.get('finish_reason')
    if finish is not None and not isinstance(finish, str):
        invalid('finish_reason must be a string or null')
    usage = body.get('usage')
    usage = usage if isinstance(usage, Mapping) else {}
    reasoning_fields, invalid_reasoning = {}, []
    for name in ('reasoning', 'reasoning_content'):
        if name not in message:
            continue
        value = message[name]
        if value is None or isinstance(value, str):
            reasoning_fields[name] = value
        else:
            invalid_reasoning.append(name)
    return ModelReply(call_id, content or '', model=body.get('model') if isinstance(body.get('model'), str) else None,
                      request_id=body.get('id') if isinstance(body.get('id'), str) else None,
                      finish_reason=finish, usage=ModelUsage(_token_count(usage.get('prompt_tokens')),
                                                            _token_count(usage.get('completion_tokens'))),
                      elapsed_s=response.elapsed_s, response_artifact=artifact,
                      reasoning=ModelReasoning(reasoning_fields, tuple(invalid_reasoning)))


def _template_subset(supplied, declared):
    return all(key in declared and value == declared[key] for key, value in supplied.items())


def load_shared_generation(template_options=None):
    """Use the official manifest loader even when no thinking fields are declared."""
    import baseline as official
    generation = official.load_generation()
    declared = generation.get('chat_template_kwargs', {})
    if template_options and not _template_subset(template_options, declared):
        raise ModelCallError('template options differ from manifest generation', kind='config')
    return generation


class ModelService:
    def __init__(self, backend: ModelBackend, recorder: RunRecorder, *,
                 timeout_limit_s: float | None = None, token_counter=None,
                 token_policy=None, context_limit=None, strict_context=False,
                 template_options=None):
        if timeout_limit_s is not None and (not math.isfinite(timeout_limit_s) or timeout_limit_s <= 0):
            raise ValueError('service timeout limit must be positive and finite')
        self.timeout_limit_s = timeout_limit_s
        self.backend, self.recorder = backend, recorder
        from agent.core.tokens import TokenLedger, UnavailableCounter
        self.counter = token_counter or UnavailableCounter()
        self.tokens = TokenLedger(token_policy)
        self.context_limit, self.strict_context = context_limit, strict_context
        self.generation = load_shared_generation(template_options)
        self.template_options = dict(self.generation.get('chat_template_kwargs', {}))
        self.requests = []
        # Programmatic configurations may use secrets absent from the environment.
        config = getattr(backend, 'config', None)
        if config is not None:
            recorder.redactor.add_secrets([config.api_key])

    def baseline_model(self, *, timeout_s: float) -> str:
        """Discovery is recorded separately and does not consume a generation ID."""
        resolver = getattr(self.backend, 'baseline_model', None)
        if resolver is None:
            model, source = self.backend.describe().get('model') or 'default', 'non_http'
        else:
            limit = min(timeout_s, self.timeout_limit_s) if self.timeout_limit_s else timeout_s
            self.recorder.write_event('model_selection', 'started', timeout_s=limit)
            start = time.monotonic()
            model, source = resolver(limit)
            self.recorder.write_event('model_selection', 'finished', model=model, source=source,
                                      elapsed_s=time.monotonic() - start)
        return model

    def chat(self, request: ModelRequest) -> ModelReply:
        for key in ('chat_template_kwargs', 'reasoning_effort'):
            supplied = getattr(request, key)
            if supplied is None:
                continue
            if key not in self.generation:
                raise ModelCallError('request adds undeclared thinking settings', kind='config')
            declared = self.generation[key]
            matches = (_template_subset(supplied, declared) if key == 'chat_template_kwargs'
                       else supplied == declared)
            if not matches:
                raise ModelCallError('request thinking settings differ from manifest generation', kind='config')
        request = replace(request, **self.generation)
        if self.timeout_limit_s is not None:
            request = replace(request, timeout_s=min(request.timeout_s, self.timeout_limit_s))
        if isinstance(self.backend, HttpBackend) and request.model is None:
            request = replace(request, model=self.backend.config.model)
        from agent.core.tokens import TokenBudgetError
        from agent.prompts.context import ContextLimitError, messages_hash
        prediction = self.counter.count(request.messages,
            template_options=request.chat_template_kwargs if request.chat_template_kwargs is not None else {})
        try:
            cap = self.tokens.allowance(prediction, request.max_tokens)
            if self.context_limit is not None:
                if self.strict_context and prediction.status != 'exact':
                    raise ContextLimitError('input_tokens_unknown')
                if prediction.status == 'exact' and prediction.value + cap > self.context_limit:
                    raise ContextLimitError('required_context_exceeds_limit')
        except (TokenBudgetError, ContextLimitError) as exc:
            self.recorder.write_event('tokens', 'denied', reason=str(exc), prediction=prediction.public_dict())
            raise
        if cap != request.max_tokens:
            request = replace(request, max_tokens=cap)
        payload = (request.payload(self.backend.config.model)
                   if isinstance(self.backend, HttpBackend) and request.profile == 'baseline_rtl' else None)
        service_info = dict(self.backend.describe())
        if request.model is not None:
            service_info['model'] = request.model
        call = self.recorder.begin_call(request, service_info, http_payload=payload)
        self.requests.append(dict(call_id=call.call_id, request=request.public_dict()))
        self.tokens.start(call.call_id, predicted_input=prediction, output_cap=request.max_tokens)
        self.recorder.write_event('tokens', 'reserved', call_id=call.call_id,
            prediction=prediction.public_dict(), output_cap=request.max_tokens,
            messages_sha256=messages_hash(request.messages))
        artifact = None
        response = None
        try:
            response = self.backend.complete(request)
            body, json_valid = None, False
            if response.mock_content is None:
                # Parsing even an HTTP error's JSON preserves all diagnostic fields.
                try:
                    body = json.loads(response.raw_text)
                    json_valid = True
                except (ValueError, TypeError):
                    body = None
            artifact = self.recorder.record_response(call, response, body if json_valid else None)
            if response.mock_content is not None:
                reply = ModelReply(call.call_id, response.mock_content,
                                   model=self.backend.describe().get('model'),
                                   finish_reason='stop', elapsed_s=response.elapsed_s)
            else:
                if response.status_code != 200:
                    raise ModelCallError(f'model service returned HTTP {response.status_code}', kind='http',
                                         status_code=response.status_code,
                                         retryable=response.status_code in {408, 425, 429, 500, 502, 503, 504},
                                         elapsed_s=response.elapsed_s)
                if not json_valid:
                    raise ModelCallError('model service returned invalid JSON', kind='json',
                                         elapsed_s=response.elapsed_s)
                reply = _parse_reply(body, call.call_id, response, artifact)
        except ModelCallError as exc:
            exc.call_id = call.call_id
            exc.evidence = artifact
            if exc.status_code is None and response is not None:
                exc.status_code = response.status_code
            self.recorder.finish_call(call, exc)
            self.tokens.finish(call.call_id, outcome='failed')
            self.recorder.write_event('tokens', 'settled', call_id=call.call_id, snapshot=self.tokens.snapshot())
            raise
        except RecordingError:
            raise
        except Exception as exc:
            # A programming failure still ends the call with a classified record.
            error = ModelCallError(f'unexpected model backend failure ({type(exc).__name__})', call_id=call.call_id,
                                   kind='backend', evidence=artifact,
                                   elapsed_s=response.elapsed_s if response else 0.0)
            self.recorder.finish_call(call, error)
            self.tokens.finish(call.call_id, outcome='failed')
            self.recorder.write_event('tokens', 'settled', call_id=call.call_id, snapshot=self.tokens.snapshot())
            raise error from exc
        self.recorder.finish_call(call, reply)
        self.tokens.finish(call.call_id, usage=reply.usage, outcome='succeeded')
        if self.tokens.snapshot()['blocked'] and callable(getattr(self.counter, 'mark_mismatch', None)):
            self.counter.mark_mismatch()
        self.recorder.write_event('tokens', 'settled', call_id=call.call_id, snapshot=self.tokens.snapshot())
        return reply
