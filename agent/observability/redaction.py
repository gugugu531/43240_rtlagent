"""Sanitize recording copies, never the model's input or output."""

from collections.abc import Mapping
import os
import re
from urllib.parse import urlsplit, urlunsplit

SENSITIVE = {
    "api_key",
    "authorization",
    "cookie",
    "set_cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "rc_cookie",
    "rc_api_key",
    "fpgachina_token",
    "rtlagent_ui_operator_token",
}
ENV_SECRETS = (
    "LLM_API_KEY",
    "FPGACHINA_TOKEN",
    "RTLAGENT_UI_OPERATOR_TOKEN",
    "RC_COOKIE",
    "RC_API_KEY",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = set(
            v for v in [*(os.environ.get(k, "") for k in ENV_SECRETS), *secrets] if v
        )

    def add_secrets(self, secrets):
        self.secrets.update(v for v in secrets if v)

    def _collect(self, value, key=None):
        if (
            key
            and key.lower().replace("-", "_") in SENSITIVE
            and isinstance(value, str)
        ):
            self.add_secrets([value])
            if key.lower() == "authorization" and value.lower().startswith("bearer "):
                self.add_secrets([value[7:]])
        if isinstance(value, Mapping):
            for k, v in value.items():
                self._collect(v, str(k))
        elif isinstance(value, (tuple, list)):
            for item in value:
                self._collect(item)

    def copy(self, value):
        self._collect(value)
        return self._copy(value)

    def _copy(self, value, key=None):
        if key and key.lower().replace("-", "_") in SENSITIVE:
            return "[redacted]"
        if isinstance(value, Mapping):
            return {str(k): self._copy(v, str(k)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._copy(v) for v in value]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, "[redacted]")
            # Also sanitize unstructured JSON/text, e.g. HTML HTTP errors.
            value = re.sub(
                r'(?i)(authorization|set[_-]?cookie|cookie|api[_-]?key|password|secret|access_token|refresh_token|token)(["\s:=]+)[^\r\n,}\"]+',
                r"\1\2[redacted]",
                value,
            )

            def clean_url(match):
                try:
                    u = urlsplit(match.group(0))
                    host = u.netloc.rsplit("@", 1)[-1]
                    return urlunsplit((u.scheme, host, u.path, "", ""))
                except ValueError:
                    return "[invalid-url]"

            return re.sub(r'https?://[^\s"<>]+', clean_url, value)
        return value
