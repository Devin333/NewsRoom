from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from business.foundation.models.source import SourceError


def normalize_source_errors(
    values: Any,
    *,
    context: str = "source_errors",
) -> list[SourceError]:
    if values is None:
        return []
    if isinstance(values, SourceError | Mapping) or isinstance(
        values, (str, bytes, bytearray)
    ):
        raise TypeError(
            f"{context} must be a sequence of SourceError or mapping values"
        )
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


def _source_error_from_mapping(
    value: Mapping[str, Any], *, context: str
) -> SourceError:
    _require_source_error_fields(value, context=context)
    metadata = _metadata(value.get("metadata"), context=context)
    retryable = _retryable_value(value, metadata=metadata, context=context)
    kwargs: dict[str, Any] = {
        "source_id": str(value["source_id"]),
        "source_name": _optional_str(value.get("source_name")),
        "error_type": str(value["error_type"]),
        "error_message": str(value["error_message"]),
        "url": _optional_str(value.get("url")),
        "retryable": retryable,
        "request_ref": value.get("request_ref"),
        "response_ref": value.get("response_ref"),
        "metadata": metadata,
    }
    occurred_at = value.get("occurred_at")
    if occurred_at is not None:
        kwargs["occurred_at"] = _aware_datetime(occurred_at, context=context)
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


def _metadata(value: Any, *, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} entry metadata must be a mapping")
    return dict(value)


def _retryable_value(
    value: Mapping[str, Any],
    *,
    metadata: dict[str, Any],
    context: str,
) -> bool:
    if value.get("retryable") is not None:
        retryable = _boolean(value["retryable"], context=f"{context} retryable")
    elif metadata.get("retryable") is not None:
        retryable = _boolean(
            metadata["retryable"], context=f"{context} metadata.retryable"
        )
    else:
        retryable = True
    if "retryable" in metadata:
        metadata["retryable"] = retryable
    return retryable


def _boolean(value: Any, *, context: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{context} must be a boolean or documented boolean string")


def _aware_datetime(value: Any, *, context: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} occurred_at must be an ISO 8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} occurred_at must be an ISO 8601 datetime") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


_REQUIRED_FIELDS = ("source_id", "error_type", "error_message")


__all__ = ["normalize_source_errors"]
