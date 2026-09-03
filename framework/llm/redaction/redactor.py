from __future__ import annotations

from typing import Any

from framework.shared.redaction import RedactionRule, Redactor


REDACTED_VALUE = "[redacted]"
SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "dsn",
    "password",
    "secret",
    "token",
)
NON_SENSITIVE_TOKEN_KEYS = {
    "cached_input_tokens",
    "completion_tokens",
    "input_tokens",
    "max_input_tokens",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "media_tokens",
    "message_tokens",
    "operational_limit_tokens",
    "output_tokens",
    "physical_limit_tokens",
    "prompt_tokens",
    "provider_reported_limit_tokens",
    "provider_reported_usage_tokens",
    "protocol_overhead_tokens",
    "reasoning_tokens",
    "requested_output_tokens",
    "reserved_output_tokens",
    "response_schema_tokens",
    "safety_margin_tokens",
    "token_count",
    "token_usage",
    "tokenizer_family",
    "tokenizer_revision",
    "tool_tokens",
    "total_tokens",
}

_REDACTOR = Redactor(
    [
        RedactionRule(
            key_tokens=SENSITIVE_KEY_FRAGMENTS,
            replacement=REDACTED_VALUE,
        )
    ]
)


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE if _is_sensitive_key(key) else redact_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_values(item) for item in value)
    return _REDACTOR.redact(value)


class LLMRedactor:
    def redact_request(self, request):
        from framework.llm.models.request import LLMRequest

        return LLMRequest.from_dict(redact_sensitive_values(request.to_dict(redact=False)))

    def redact_response(self, response):
        from framework.llm.models.response import LLMResponse

        return LLMResponse.from_dict(redact_sensitive_values(response.to_dict(redact=False)))


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if normalized in NON_SENSITIVE_TOKEN_KEYS:
        return False
    return _REDACTOR.contains_sensitive_key({str(key): None})
