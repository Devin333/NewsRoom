from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.foundation.models.source import SourceError


def normalize_source_errors(
    values: Any,
    *,
    context: str = "source_errors",
) -> list[SourceError]:
    if values is None:
        return []
    if isinstance(values, SourceError | Mapping) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{context} must be a sequence of SourceError or mapping values")
    try:
        error_values = list(values)
    except TypeError as exc:
        raise TypeError(
            f"{context} must be a sequence of SourceError or mapping values"
        ) from exc
    return [_normalize_source_error(value, context=context) for value in error_values]


def _normalize_source_error(value: Any, *, context: str) -> SourceError:
    if isinstance(value, SourceError):
        return value
    if isinstance(value, Mapping):
        return _source_error_from_mapping(value, context=context)
    raise TypeError(f"{context} entries must be SourceError or mapping values")


def _source_error_from_mapping(value: Mapping[str, Any], *, context: str) -> SourceError:
    _require_source_error_fields(value, context=context)
    kwargs: dict[str, Any] = {
        "source_id": str(value["source_id"]),
        "source_name": _optional_str(value.get("source_name")),
        "error_type": str(value["error_type"]),
        "error_message": str(value["error_message"]),
        "url": _optional_str(value.get("url")),
        "retryable": value.get("retryable"),
        "request_ref": value.get("request_ref"),
        "response_ref": value.get("response_ref"),
        "metadata": dict(value.get("metadata") or {}),
    }
    occurred_at = value.get("occurred_at")
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    return SourceError(**kwargs)


def _require_source_error_fields(value: Mapping[str, Any], *, context: str) -> None:
    missing = [field_name for field_name in _REQUIRED_FIELDS if field_name not in value]
    if missing:
        raise TypeError(
            f"{context} entries must include {', '.join(_REQUIRED_FIELDS)}; "
            f"missing {', '.join(missing)}"
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_REQUIRED_FIELDS = ("source_id", "error_type", "error_message")


__all__ = ["normalize_source_errors"]
