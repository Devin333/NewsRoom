from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceConnectorDispatchReport


def build_source_connector_dispatch_report(
    fetch_requests: list[Any],
    fetch_results: list[Any],
) -> SourceConnectorDispatchReport:
    results_by_request_id = {
        _value(result, "request_id"): result
        for result in fetch_results
        if _value(result, "request_id") is not None
    }
    rows: list[dict[str, Any]] = []
    connector_counts: dict[str, int] = {}
    success_by_connector: dict[str, int] = {}
    failed_by_connector: dict[str, int] = {}
    skipped_by_connector: dict[str, int] = {}

    for request in fetch_requests:
        request_id = str(_value(request, "request_id") or "")
        result = results_by_request_id.get(request_id)
        connector_name = _connector_name(request)
        success = bool(_value(result, "success")) if result is not None else False
        skipped = bool(_value(result, "skipped")) if result is not None else False
        error_type = _value(result, "error_type") if result is not None else "missing_fetch_result"

        _increment(connector_counts, connector_name)
        if skipped:
            _increment(skipped_by_connector, connector_name)
        elif success:
            _increment(success_by_connector, connector_name)
        else:
            _increment(failed_by_connector, connector_name)

        rows.append(
            {
                "request_id": request_id,
                "source_id": _value(request, "source_id"),
                "source_type": _source_type_value(_value(request, "source_type")),
                "connector_name": connector_name,
                "success": success,
                "skipped": skipped,
                "skip_reason": _value(result, "skip_reason") if result is not None else None,
                "error_type": error_type,
            }
        )

    return SourceConnectorDispatchReport(
        total_dispatch_count=len(rows),
        success_count=sum(1 for row in rows if row["success"] and not row["skipped"]),
        failed_count=sum(1 for row in rows if not row["success"] and not row["skipped"]),
        skipped_count=sum(1 for row in rows if row["skipped"]),
        connector_counts=connector_counts,
        success_by_connector=success_by_connector,
        failed_by_connector=failed_by_connector,
        skipped_by_connector=skipped_by_connector,
        rows=rows,
    )


def _connector_name(request: Any) -> str:
    connector_name = _optional_text(_value(request, "connector_name"))
    if connector_name is not None:
        return connector_name
    metadata_connector_name = _optional_text(_metadata(request).get("connector_name"))
    if metadata_connector_name is not None:
        return metadata_connector_name
    return str(_value(request, "source_type") or "unknown")


def _metadata(value: Any) -> dict[str, Any]:
    metadata = _value(value, "metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _value(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _source_type_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _increment(metrics: dict[str, int], key: str) -> None:
    metrics[key] = metrics.get(key, 0) + 1
