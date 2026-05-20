from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceHealthReport


def build_source_health_report(source_health_updates: list[Any]) -> SourceHealthReport:
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    down_source_ids: list[str] = []
    cooling_down_source_ids: list[str] = []
    degraded_source_ids: list[str] = []
    disabled_source_ids: list[str] = []

    for health in source_health_updates:
        status = _status_value(_value(health, "status"))
        if status == "cooling_down":
            status = "down"
        source_id = str(_value(health, "source_id") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "down" and source_id:
            down_source_ids.append(source_id)
            cooling_down_source_ids.append(source_id)
        elif status == "degraded" and source_id:
            degraded_source_ids.append(source_id)
        elif status == "disabled" and source_id:
            disabled_source_ids.append(source_id)
        last_error = _value(health, "last_error")
        consecutive_failures = int(
            _value(health, "consecutive_failures")
            or _value(health, "consecutive_failure_count")
            or 0
        )
        metadata = _value(health, "metadata")
        rows.append(
            {
                "source_id": source_id,
                "source_name": _value(health, "source_name"),
                "url": _value(health, "url"),
                "status": status,
                "health_status": status,
                "consecutive_failures": consecutive_failures,
                "consecutive_failure_count": consecutive_failures,
                "success_count_24h": int(_value(health, "success_count_24h") or 0),
                "failure_count_24h": int(_value(health, "failure_count_24h") or 0),
                "avg_latency_ms_24h": _value(health, "avg_latency_ms_24h"),
                "cooldown_until": _dt(_value(health, "cooldown_until")),
                "last_error_type": _value(last_error, "error_type") if last_error is not None else None,
                "last_error_message": (
                    _value(last_error, "error_message") if last_error is not None else None
                ),
                "metadata": dict(metadata) if isinstance(metadata, dict) else {},
            }
        )

    return SourceHealthReport(
        health_update_count=len(rows),
        status_counts=status_counts,
        down_source_ids=sorted(set(down_source_ids)),
        cooling_down_source_ids=sorted(set(cooling_down_source_ids)),
        degraded_source_ids=sorted(set(degraded_source_ids)),
        disabled_source_ids=sorted(set(disabled_source_ids)),
        max_consecutive_failures=max(
            [int(row["consecutive_failures"]) for row in rows],
            default=0,
        ),
        rows=rows,
    )


def _value(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _status_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "unknown")


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
