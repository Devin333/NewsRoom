from __future__ import annotations

import re
from typing import Any


REDACTED_VALUE = "[redacted]"
SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
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


def contains_redacted_value(value: Any) -> bool:
    if value == REDACTED_VALUE:
        return True
    if isinstance(value, dict):
        return any(contains_redacted_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_redacted_value(item) for item in value)
    return False


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _redact_secret_like_string(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    return redacted
