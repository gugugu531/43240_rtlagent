from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.llm import (  # noqa: E402
    LLM,
    LLMConfig,
    LLMConfigError,
    LLMConnectionError,
    LLMHTTPError,
    LLMResponseError,
    LLMTimeoutError,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, text="", json_error=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._body


def openai_config(**overrides):
    values = {
        "backend": "openai",
        "model": "test-model",
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key": "",
        "max_tokens": 4096,
        "temperature": 0.2,
        "timeout_s": 180.0,
    }
    values.update(overrides)
    return LLMConfig(**values)


def success_body(content="module TopModule; endmodule", **overrides):
    body = {
        "id": "chatcmpl-test",
        "model": "served-model",
        "choices": [{
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }
    body.update(overrides)
    return body


class LLMConfigTests(unittest.TestCase):
    def test_mock_defaults(self):
        config = LLMConfig.from_env({})
        self.assertEqual(config.backend, "mock")
        self.assertEqual(config.model, "mock-model")
        self.assertEqual(config.max_tokens, 4096)
        self.assertEqual(config.timeout_s, 180.0)

    def test_openai_requires_absolute_http_url(self):
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({"LLM_BACKEND": "openai"})
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({
                "LLM_BACKEND": "openai",
                "LLM_BASE_URL": "127.0.0.1:8000/v1",
            })

    def test_numeric_configuration_is_validated(self):
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({"LLM_MAX_TOKENS": "0"})
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({"LLM_TIMEOUT_S": "nan"})
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({"LLM_TEMPERATURE": "-1"})

    def test_api_key_is_not_public(self):
        config = openai_config(api_key="top-secret")
        self.assertNotIn("top-secret", repr(config))
        self.assertNotIn("api_key", config.public_dict())
        self.assertNotIn("top-secret", str(LLM(config).describe()))


class LLMOpenAITests(unittest.TestCase):
    def test_successful_request_and_result(self):
        response = FakeResponse(body=success_body())
        client = LLM(openai_config(api_key="secret"))
        messages = [{"role": "user", "content": "write RTL"}]

        with patch("requests.post", return_value=response) as post:
            result = client.chat(
                messages,
                timeout_s=12,
                max_tokens=123,
                temperature=0.0,
            )

        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(
            post.call_args.args[0],
            "http://127.0.0.1:8000/v1/chat/completions",
        )
        self.assertEqual(kwargs["timeout"], 12.0)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["json"]["messages"], messages)
        self.assertEqual(kwargs["json"]["max_tokens"], 123)
        self.assertEqual(kwargs["json"]["temperature"], 0.0)
        self.assertFalse(kwargs["json"]["stream"])

        self.assertEqual(result.text, "module TopModule; endmodule")
        self.assertEqual(result.tokens_in, 12)
        self.assertEqual(result.tokens_out, 7)
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.finish, "stop")
        self.assertEqual(result.model, "served-model")
        self.assertEqual(result.request_id, "chatcmpl-test")
        self.assertFalse(result.empty_content)
        self.assertGreaterEqual(result.elapsed_s, 0.0)

    def test_authorization_header_is_omitted_without_key(self):
        client = LLM(openai_config())
        with patch("requests.post", return_value=FakeResponse(body=success_body())) as post:
            client.chat([{"role": "user", "content": "x"}])
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_per_call_options_do_not_mutate_defaults(self):
        client = LLM(openai_config(max_tokens=100, temperature=0.4, timeout_s=30))
        response = FakeResponse(body=success_body())
        with patch("requests.post", return_value=response) as post:
            client.chat([], timeout_s=2, max_tokens=10, temperature=0)
            client.chat([])

        first = post.call_args_list[0].kwargs
        second = post.call_args_list[1].kwargs
        self.assertEqual(first["timeout"], 2.0)
        self.assertEqual(first["json"]["max_tokens"], 10)
        self.assertEqual(first["json"]["temperature"], 0.0)
        self.assertEqual(second["timeout"], 30.0)
        self.assertEqual(second["json"]["max_tokens"], 100)
        self.assertEqual(second["json"]["temperature"], 0.4)

    def test_timeout_is_classified(self):
        client = LLM(openai_config())
        with patch("requests.post", side_effect=requests.Timeout("read timed out")):
            with self.assertRaises(LLMTimeoutError) as caught:
                client.chat([])
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.kind, "timeout")

    def test_connection_error_is_classified_and_redacted(self):
        client = LLM(openai_config(api_key="top-secret"))
        error = requests.ConnectionError("connection failed using top-secret")
        with patch("requests.post", side_effect=error):
            with self.assertRaises(LLMConnectionError) as caught:
                client.chat([])
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("top-secret", str(caught.exception))

    def test_http_errors_are_classified(self):
        cases = ((401, False), (429, True), (500, True), (503, True))
        for status, retryable in cases:
            with self.subTest(status=status):
                client = LLM(openai_config(api_key="top-secret"))
                response = FakeResponse(
                    status_code=status,
                    text="server rejected top-secret " + "x" * 1000,
                )
                with patch("requests.post", return_value=response):
                    with self.assertRaises(LLMHTTPError) as caught:
                        client.chat([])
                error = caught.exception
                self.assertEqual(error.status_code, status)
                self.assertEqual(error.retryable, retryable)
                self.assertNotIn("top-secret", str(error))
                self.assertLess(len(str(error)), 600)

    def test_invalid_json_is_response_error(self):
        response = FakeResponse(json_error=ValueError("bad json"))
        with patch("requests.post", return_value=response):
            with self.assertRaises(LLMResponseError):
                LLM(openai_config()).chat([])

    def test_invalid_response_shapes_are_rejected(self):
        bodies = [None, {}, {"choices": []}, {"choices": [{}]}]
        for body in bodies:
            with self.subTest(body=body):
                with patch("requests.post", return_value=FakeResponse(body=body)):
                    with self.assertRaises(LLMResponseError):
                        LLM(openai_config()).chat([])

    def test_null_content_preserves_finish_and_reasoning_metadata(self):
        body = success_body(None)
        body["choices"][0]["finish_reason"] = "length"
        body["choices"][0]["message"]["reasoning_content"] = "hidden reasoning"
        with patch("requests.post", return_value=FakeResponse(body=body)):
            result = LLM(openai_config()).chat([])
        self.assertEqual(result.text, "")
        self.assertTrue(result.empty_content)
        self.assertTrue(result.has_reasoning)
        self.assertEqual(result.finish_reason, "length")

    def test_missing_or_invalid_usage_falls_back_to_zero(self):
        body = success_body()
        body["usage"] = {"prompt_tokens": "bad", "completion_tokens": -2}
        with patch("requests.post", return_value=FakeResponse(body=body)):
            result = LLM(openai_config()).chat([])
        self.assertEqual(result.tokens_in, 0)
        self.assertEqual(result.tokens_out, 0)


class LLMMockTests(unittest.TestCase):
    def test_mock_uses_the_same_result_type(self):
        client = LLM(LLMConfig())
        result = client.chat([{
            "role": "user",
            "content": (
                "I would like you to implement a module named TopModule with "
                "the following interface.\n - input a\n - output q"
            ),
        }])
        self.assertIn("module TopModule", result.text)
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.model, "mock-model")
        self.assertFalse(result.empty_content)


if __name__ == "__main__":
    unittest.main()
