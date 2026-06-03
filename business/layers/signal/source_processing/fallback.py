from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.foundation.models.source import SourceError, SourceFallbackReport
from business.foundation.models.source_error_normalization import normalize_source_errors


def build_source_fallback_report(
    *,
    raw_items: list[Any],
    source_errors: list[SourceError | dict[str, Any]],
    source_selection_report: Any | None = None,
) -> SourceFallbackReport:
    rows: list[dict[str, Any]] = []
    selection_fallback = SourceSelectionFallbackInput.from_value(source_selection_report)
    if selection_fallback.fallback_used:
        rows.append(
            {
                "fallback_type": "source_selection",
                "source_id": None,
                "fallback_reason": selection_fallback.fallback_reason,
                "metadata": {
                    "selected_source_ids": list(selection_fallback.selected_source_ids),
                },
            }
        )

    item_fallback_count = 0
    for item in SourceItemFallbackInput.from_values(raw_items):
        if not item.has_official_blog_fallback:
            continue
        item_fallback_count += 1
        rows.append(
            {
                "fallback_type": "official_blog_fetch",
                "source_id": item.source_id,
                "source_item_id": item.source_item_id,
                "from": item.from_mode,
                "to": item.to_mode,
                "feed_error_types": list(item.feed_error_types),
                "metadata": {"fetch_mode": item.fetch_mode},
            }
        )

    error_fallback_count = 0
    for error in SourceErrorFallbackInput.from_values(source_errors):
        if not error.official_blog_fallback_stage:
            continue
        error_fallback_count += 1
        rows.append(
            {
                "fallback_type": "official_blog_failed_stage",
                "source_id": error.source_id,
                "error_type": error.error_type,
                "stage": error.official_blog_fallback_stage,
                "metadata": {"retryable": error.retryable},
            }
        )

    return SourceFallbackReport(
        total_fallback_count=len(rows),
        selection_fallback_used=selection_fallback.fallback_used,
        selection_fallback_reason=selection_fallback.fallback_reason,
        item_fallback_count=item_fallback_count,
        error_fallback_count=error_fallback_count,
        rows=rows,
    )


@dataclass(frozen=True)
class SourceSelectionFallbackInput:
    fallback_used: bool = False
    fallback_reason: str | None = None
    selected_source_ids: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: Any | None) -> "SourceSelectionFallbackInput":
        if value is None:
            return cls()
        selected_source_ids = _string_tuple(_value(value, "selected_source_ids"))
        fallback_reason = _optional_text(_value(value, "fallback_reason"))
        return cls(
            fallback_used=bool(_value(value, "fallback_used")),
            fallback_reason=fallback_reason,
            selected_source_ids=selected_source_ids,
        )


@dataclass(frozen=True)
class SourceItemFallbackInput:
    source_id: str | None = None
    source_item_id: str | None = None
    fetch_mode: str | None = None
    from_mode: Any = None
    to_mode: Any = None
    feed_error_types: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_official_blog_fallback(self) -> bool:
        return isinstance(self.metadata.get("official_blog_fallback"), dict)

    @classmethod
    def from_values(cls, values: list[Any]) -> list["SourceItemFallbackInput"]:
        return [cls.from_value(value) for value in values]

    @classmethod
    def from_value(cls, value: Any) -> "SourceItemFallbackInput":
        metadata = _metadata(value)
        fallback = metadata.get("official_blog_fallback")
        fallback_payload = dict(fallback) if isinstance(fallback, dict) else {}
        return cls(
            source_id=_optional_text(_value(value, "source_id")),
            source_item_id=_optional_text(_value(value, "source_item_id")),
            fetch_mode=_optional_text(metadata.get("official_blog_fetch_mode")),
            from_mode=fallback_payload.get("from"),
            to_mode=fallback_payload.get("to"),
            feed_error_types=tuple(fallback_payload.get("feed_error_types") or ()),
            metadata=metadata,
        )


@dataclass(frozen=True)
class SourceErrorFallbackInput:
    source_id: str
    error_type: str
    retryable: bool
    official_blog_fallback_stage: str | None = None

    @classmethod
    def from_values(cls, values: list[SourceError | dict[str, Any]]) -> list["SourceErrorFallbackInput"]:
        return [cls.from_error(error) for error in normalize_source_errors(values)]

    @classmethod
    def from_error(cls, error: SourceError) -> "SourceErrorFallbackInput":
        metadata = dict(error.metadata)
        return cls(
            source_id=error.source_id,
            error_type=error.error_type,
            retryable=bool(error.retryable),
            official_blog_fallback_stage=_optional_text(
                metadata.get("official_blog_fallback_stage")
            ),
        )


def _metadata(value: Any) -> dict[str, Any]:
    metadata = _value(value, "metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


__all__ = [
    "SourceErrorFallbackInput",
    "SourceItemFallbackInput",
    "SourceSelectionFallbackInput",
    "build_source_fallback_report",
]
