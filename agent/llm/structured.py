"""约束解码与 pydantic 校验；只对格式或语义错误重问。"""

from __future__ import annotations

import copy
import json

from pydantic import ValidationError

from .types import ModelError, _get


class StructuredError(ModelError):
    pass


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)


def ask(
    client,
    messages,
    schema,
    *,
    purpose="structured",
    max_attempts=2,
    semantic_check=None,
    **chat_kwargs,
):
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    conversation = copy.deepcopy(messages)
    if _get(client.config, "structured_outputs", True):
        chat_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                "strict": True,
            },
        }
    else:
        conversation.append(
            {
                "role": "user",
                "content": "Return only JSON matching this schema:\n"
                + json.dumps(schema.model_json_schema(), ensure_ascii=False),
            }
        )
    last_error = ""
    for attempt in range(max_attempts):
        reply = client.chat(conversation, purpose=purpose, **chat_kwargs)
        error_kind = "invalid_json"
        try:
            if reply.finish_reason == "content_filter":
                error_kind = "refusal"
                raise ValueError("output refused by content filter")
            if not reply.content.strip():
                error_kind = "empty_content"
                raise ValueError("empty final content")
            if reply.finish_reason == "length":
                error_kind = "length"
                raise ValueError("output truncated by length limit")
            data = strict_json(reply.content)
            error_kind = "schema"
            result = schema.model_validate(data, strict=True)
            if semantic_check is not None:
                error_kind = "semantic"
                semantic_check(result)
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            client.record.emit(
                "structured",
                "invalid",
                call_id=reply.call_id,
                purpose=purpose,
                attempt=attempt + 1,
                error_kind=error_kind,
                finish_reason=reply.finish_reason,
                rc=1,
                excerpt=last_error[:2000],
            )
            if attempt + 1 < max_attempts:
                conversation.extend(
                    [
                        {"role": "assistant", "content": reply.content},
                        {
                            "role": "user",
                            "content": "The response failed validation. Return a corrected JSON "
                            "object using the same task constraints. Validation errors:\n"
                            + last_error,
                        },
                    ]
                )
        else:
            client.record.emit(
                "structured",
                "validated",
                call_id=reply.call_id,
                purpose=purpose,
                attempt=attempt + 1,
                rc=0,
            )
            return result
    raise StructuredError(
        "structured response invalid: " + last_error,
        kind=error_kind,
        call_id=reply.call_id,
    )
