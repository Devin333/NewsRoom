"""Sanitization helpers for shared agent session content."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SENSITIVE_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
    "authorization",
    "password",
}

SENSITIVE_NORMALIZED_FIELD_NAMES = {
    "rawpayload",
    "rawcontent",
    "rawhtml",
    "fulltext",
    "secret",
    "apikey",
    "token",
    "authorization",
    "password",
}

DEFAULT_MAX_STRING_LENGTH = 8000
TRUNCATION_SUFFIX = "...[truncated]"


def sanitize_session_content(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a sanitized copy of mapping content suitable for shared sessions."""

    return _sanitize_mapping(value, max_string_length=DEFAULT_MAX_STRING_LENGTH)


def _sanitize_value(value: Any, *, max_string_length: int) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, max_string_length=max_string_length)
    if isinstance(value, list):
        return [_sanitize_value(item, max_string_length=max_string_length) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, max_string_length=max_string_length) for item in value]
    if isinstance(value, str):
        return _truncate_string(value, max_string_length=max_string_length)
    return value


def _sanitize_mapping(value: Mapping[str, Any], *, max_string_length: int) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if _is_sensitive_field_name(key_text):
            continue
        cleaned[key_text] = _sanitize_value(item, max_string_length=max_string_length)
    return cleaned


def _is_sensitive_field_name(key: str) -> bool:
    normalized = "".join(char for char in key.casefold() if char.isalnum())
    return (
        key.casefold() in SENSITIVE_FIELD_NAMES
        or normalized in SENSITIVE_NORMALIZED_FIELD_NAMES
        or normalized.endswith("token")
        or normalized.endswith("apikey")
        or normalized.endswith("secret")
        or normalized.endswith("password")
        or "authorization" in normalized
    )


def _truncate_string(value: str, *, max_string_length: int) -> str:
    if len(value) <= max_string_length:
        return value
    limit = max(0, max_string_length - len(TRUNCATION_SUFFIX))
    return f"{value[:limit]}{TRUNCATION_SUFFIX}"
