"""Sanitization helpers for shared agent session content."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


SENSITIVE_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "raw_full_text",
    "pdf_bytes",
    "file_bytes",
    "secret",
    "api_key",
    "token",
    "authorization",
    "password",
    "cookie",
    "set_cookie",
}

SENSITIVE_NORMALIZED_FIELD_NAMES = {
    "rawpayload",
    "rawcontent",
    "rawhtml",
    "fulltext",
    "rawfulltext",
    "pdfbytes",
    "filebytes",
    "secret",
    "apikey",
    "token",
    "authorization",
    "password",
    "cookie",
    "setcookie",
}

DEFAULT_MAX_STRING_LENGTH = 8000
TRUNCATION_SUFFIX = "...[truncated]"
REDACTED_VALUE = "[redacted]"


@dataclass(frozen=True)
class SanitizedSessionContent:
    """Sanitized content and a list of redacted field paths."""

    content: dict[str, Any]
    redacted_fields: tuple[str, ...]


def sanitize_session_content(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a sanitized copy of mapping content suitable for shared sessions."""

    return sanitize_session_content_with_report(value).content


def sanitize_session_content_with_report(
    value: Mapping[str, Any],
    *,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
) -> SanitizedSessionContent:
    """Return sanitized content and redacted field paths."""

    redacted_fields: list[str] = []
    content = _sanitize_mapping(value, max_string_length=max_string_length, redacted_fields=redacted_fields, path="")
    return SanitizedSessionContent(content=content, redacted_fields=tuple(redacted_fields))


def _sanitize_value(value: Any, *, max_string_length: int, redacted_fields: list[str], path: str) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, max_string_length=max_string_length, redacted_fields=redacted_fields, path=path)
    if isinstance(value, list):
        return [_sanitize_value(item, max_string_length=max_string_length, redacted_fields=redacted_fields, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [_sanitize_value(item, max_string_length=max_string_length, redacted_fields=redacted_fields, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        return _truncate_string(value, max_string_length=max_string_length)
    if isinstance(value, bytes):
        redacted_fields.append(path or "<bytes>")
        return REDACTED_VALUE
    return value


def _sanitize_mapping(value: Mapping[str, Any], *, max_string_length: int, redacted_fields: list[str], path: str) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        field_path = f"{path}.{key_text}" if path else key_text
        if _is_sensitive_field_name(key_text):
            redacted_fields.append(field_path)
            continue
        cleaned[key_text] = _sanitize_value(item, max_string_length=max_string_length, redacted_fields=redacted_fields, path=field_path)
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
