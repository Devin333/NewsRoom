from __future__ import annotations

import re
from typing import Any


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
    "max_output_tokens",
    "output_tokens",
    "prompt_tokens",
    "reasoning_tokens",
    "token_usage",
    "total_tokens",
}

_SECRET_PREFIX = "sk" + "-"
_SECRET_PATTERNS = (
    re.compile(rf"{_SECRET_PREFIX}[A-Za-z0-9_-]{{8,}}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"([a-z][a-z0-9+.-]*://)([^/\s:@?#]+):([^@\s/?#]+)@", re.IGNORECASE),
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
    if isinstance(value, str):
        return _redact_secret_like_string(value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if normalized in NON_SENSITIVE_TOKEN_KEYS:
        return False
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _redact_secret_like_string(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(REDACTED_VALUE, redacted)
    redacted = _SECRET_PATTERNS[1].sub(REDACTED_VALUE, redacted)
    redacted = _SECRET_PATTERNS[2].sub(lambda match: f"{match.group(1)}{REDACTED_VALUE}@", redacted)
    return redacted
