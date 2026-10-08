"""One model call, transport evidence first, protocol validation second."""
from __future__ import annotations
import json
import time
from dataclasses import replace
import math
from collections.abc import Mapping
from agent.core.config import ModelConfig
from agent.core.model import (BackendResponse, ModelBackend, ModelCallError, ModelReply,
                          ModelRequest, ModelUsage)
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

    def complete(self, request: ModelRequest):
        import requests
        headers = {'Content-Type': 'application/json'}
        if self.config.api_key:
            headers['Authorization'] = f'Bearer {self.config.api_key}'
        start = time.monotonic()
        try:
            response = requests.post(
                self.config.base_url + '/chat/completions', headers=headers,
                json=dict(model=self.config.model, messages=request.public_dict()['messages'],
                          max_tokens=request.max_tokens, temperature=request.temperature, stream=False),
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
    return ModelReply(call_id, content or '', model=body.get('model') if isinstance(body.get('model'), str) else None,
                      request_id=body.get('id') if isinstance(body.get('id'), str) else None,
                      finish_reason=finish, usage=ModelUsage(_token_count(usage.get('prompt_tokens')),
                                                            _token_count(usage.get('completion_tokens'))),
                      elapsed_s=response.elapsed_s, response_artifact=artifact)


class ModelService:
    def __init__(self, backend: ModelBackend, recorder: RunRecorder, *,
                 timeout_limit_s: float | None = None):
        if timeout_limit_s is not None and (not math.isfinite(timeout_limit_s) or timeout_limit_s <= 0):
            raise ValueError('service timeout limit must be positive and finite')
        self.timeout_limit_s = timeout_limit_s
        self.backend, self.recorder = backend, recorder
        # Programmatic configurations may use secrets absent from the environment.
        config = getattr(backend, 'config', None)
        if config is not None:
            recorder.redactor.add_secrets([config.api_key])

    def chat(self, request: ModelRequest) -> ModelReply:
        if self.timeout_limit_s is not None:
            request = replace(request, timeout_s=min(request.timeout_s, self.timeout_limit_s))
        call = self.recorder.begin_call(request, self.backend.describe())
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
            raise
        except RecordingError:
            raise
        except Exception as exc:
            # A programming failure still ends the call with a classified record.
            error = ModelCallError(f'unexpected model backend failure ({type(exc).__name__})', call_id=call.call_id,
                                   kind='backend', evidence=artifact,
                                   elapsed_s=response.elapsed_s if response else 0.0)
            self.recorder.finish_call(call, error)
            raise error from exc
        self.recorder.finish_call(call, reply)
        return reply
