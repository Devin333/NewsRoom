from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceFallbackReport


def build_source_fallback_report(
    *,
    raw_items: list[Any],
    source_errors: list[Any],
    source_selection_report: Any | None = None,
) -> SourceFallbackReport:
    rows: list[dict[str, Any]] = []
    selection_fallback_used = _selection_fallback_used(source_selection_report)
    selection_fallback_reason = _selection_fallback_reason(source_selection_report)
    if selection_fallback_used:
        rows.append(
            {
                "fallback_type": "source_selection",
                "source_id": None,
                "fallback_reason": selection_fallback_reason,
                "metadata": {
                    "selected_source_ids": _selection_selected_source_ids(source_selection_report),
                },
            }
        )

    item_fallback_count = 0
    for item in raw_items:
        metadata = _metadata(item)
        fallback = metadata.get("official_blog_fallback")
        if not isinstance(fallback, dict):
            continue
        item_fallback_count += 1
        rows.append(
            {
                "fallback_type": "official_blog_fetch",
                "source_id": _value(item, "source_id"),
                "source_item_id": _value(item, "source_item_id"),
                "from": fallback.get("from"),
                "to": fallback.get("to"),
                "feed_error_types": list(fallback.get("feed_error_types") or []),
                "metadata": {"fetch_mode": metadata.get("official_blog_fetch_mode")},
            }
        )

    error_fallback_count = 0
    for error in source_errors:
        metadata = _metadata(error)
        stage = metadata.get("official_blog_fallback_stage")
        if not stage:
            continue
        error_fallback_count += 1
        rows.append(
            {
                "fallback_type": "official_blog_failed_stage",
                "source_id": _value(error, "source_id"),
                "error_type": _value(error, "error_type"),
                "stage": stage,
                "metadata": {"retryable": _value(error, "retryable")},
            }
        )

    return SourceFallbackReport(
        total_fallback_count=len(rows),
        selection_fallback_used=selection_fallback_used,
        selection_fallback_reason=selection_fallback_reason,
        item_fallback_count=item_fallback_count,
        error_fallback_count=error_fallback_count,
        rows=rows,
    )


def _selection_fallback_used(report: Any | None) -> bool:
    value = _report_value(report, "fallback_used")
    return bool(value)


def _selection_fallback_reason(report: Any | None) -> str | None:
    value = _report_value(report, "fallback_reason")
    return str(value) if value is not None else None


def _selection_selected_source_ids(report: Any | None) -> list[str]:
    value = _report_value(report, "selected_source_ids")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _report_value(report: Any | None, name: str) -> Any:
    if report is None:
        return None
    if isinstance(report, dict):
        return report.get(name)
    return getattr(report, name, None)


def _metadata(value: Any) -> dict[str, Any]:
    metadata = _value(value, "metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
