"""Offline text-chat counting from local tokenizer data, without remote code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent.core.tokens import TokenCount


class LocalTokenCounter:
    def __init__(self, directory, *, expected_tokenizer_sha256=None, expected_template_sha256=None):
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from tokenizers import Tokenizer
        root = Path(directory)
        data = (root / 'tokenizer.json').read_bytes()
        config = json.loads((root / 'tokenizer_config.json').read_text())
        template = config.get('chat_template')
        if not isinstance(template, str) or not template:
            raise ValueError('a single local chat template is required')
        self.tokenizer_sha256 = hashlib.sha256(data).hexdigest()
        self.template_sha256 = hashlib.sha256(template.encode()).hexdigest()
        if ((expected_tokenizer_sha256 and self.tokenizer_sha256 != expected_tokenizer_sha256)
                or (expected_template_sha256 and self.template_sha256 != expected_template_sha256)):
            raise ValueError('tokenizer identity mismatch')
        self._tokenizer = Tokenizer.from_str(data.decode())
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                            extensions=['jinja2.ext.loopcontrols'])
        env.filters['tojson'] = lambda value, **kwargs: json.dumps(value, ensure_ascii=False, **kwargs)
        def fail(message):
            raise ValueError(message)
        env.globals['raise_exception'] = fail
        self._template = env.from_string(template)
        self._special = {k: v.get('content') if isinstance(v, dict) else v
                         for k, v in config.items() if k.endswith('_token')}
        self._mismatch = False

    def mark_mismatch(self):
        self._mismatch = True

    def count(self, messages, *, template_options=None):
        identity = dict(tokenizer_sha256=self.tokenizer_sha256, template_sha256=self.template_sha256)
        if self._mismatch:
            return TokenCount(status='mismatch', reason='service_usage_mismatch', **identity)
        # Restrict this adapter to the text-only contract used by the RTL agent.
        if not messages or any(m.get('role') not in ('system', 'user', 'assistant')
                               or not isinstance(m.get('content'), str)
                               or set(m) - {'role', 'content'} for m in messages):
            return TokenCount(reason='unsupported_chat_shape', **identity)
        options = dict(template_options or {})
        if any(not isinstance(key, str) or type(value) not in (bool, int, float, str)
               for key, value in options.items()):
            return TokenCount(reason='unsupported_template_options', **identity)
        try:
            rendered = self._template.render(messages=[dict(m) for m in messages],
                add_generation_prompt=True, **self._special, **options)
            # The template already supplies special tokens. Do not add them twice.
            count = len(self._tokenizer.encode(rendered, add_special_tokens=False).ids)
            return TokenCount(count, 'exact', **identity)
        except Exception as exc:
            return TokenCount(reason=f'template_failed:{type(exc).__name__}', **identity)
