from __future__ import annotations

from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.sources import SourceError, SourceHealth
from storage.repository import ReportRecord


class PostgresReportRepository(Protocol):
    def save_report(self, record: ReportRecord) -> None: ...


class PostgresSourceHealthRepository(Protocol):
    def update_source_health(self, health: SourceHealth) -> None: ...


def register_postgres_tools(
    registry: ToolRegistry,
    *,
    repository: PostgresReportRepository,
    source_health_repository: PostgresSourceHealthRepository | None = None,
) -> None:
    for tool_name in ["postgres.save_report", "postgres.insert_report"]:
        registry.register(
            ToolDefinition(
                name=tool_name,
                description="Save a typed report record through the configured PostgreSQL repository.",
                input_schema=_report_schema(),
                side_effect="writes_external_state",
                requires_approval=True,
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"writes_postgres_report": True},
            ),
            lambda args, tool_name=tool_name: _save_report(
                args,
                repository=repository,
                tool_name=tool_name,
            ),
        )
    health_repository = source_health_repository or (
        repository if hasattr(repository, "update_source_health") else None
    )
    if health_repository is not None:
        registry.register(
            ToolDefinition(
                name="postgres.update_source_health",
                description="Update a typed source health record through the configured PostgreSQL repository.",
                input_schema={
                    "required": ["source_id", "status"],
                    "properties": {
                        "source_id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["healthy", "degraded", "down", "cooling_down", "disabled"],
                        },
                        "consecutive_failures": {"type": "integer"},
                        "success_count_24h": {"type": "integer"},
                        "failure_count_24h": {"type": "integer"},
                        "avg_latency_ms_24h": {"type": "number"},
                        "last_success_at": {"type": "string"},
                        "last_failure_at": {"type": "string"},
                        "cooldown_until": {"type": "string"},
                        "last_error": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_external_state",
                requires_approval=True,
                concurrency_safe=False,
                max_result_bytes=100_000,
                metadata={"writes_postgres_source_health": True},
            ),
            lambda args: _update_source_health(
                args,
                repository=health_repository,
            ),
        )


def _report_schema() -> dict[str, Any]:
    return {
        "required": ["report_id", "run_id", "status", "report_json"],
        "properties": {
            "report_id": {"type": "string"},
            "run_id": {"type": "string"},
            "status": {"type": "string"},
            "title": {"type": "string"},
            "report_json": {"type": "object"},
            "report_markdown": {"type": "string"},
            "quality_score": {"type": "number"},
            "citation_coverage_score": {"type": "number"},
            "manifest_path": {"type": "string"},
        },
        "additionalProperties": False,
    }


def _save_report(
    args: dict[str, Any],
    *,
    repository: PostgresReportRepository,
    tool_name: str,
) -> dict[str, Any]:
    report_id = _required_text(args.get("report_id"), "report_id")
    run_id = _required_text(args.get("run_id"), "run_id")
    status = _required_text(args.get("status"), "status")
    report_json = args["report_json"]
    if not isinstance(report_json, dict):
        raise ValueError("report_json must be an object")
    record = ReportRecord(
        report_id=report_id,
        run_id=run_id,
        status=status,
        title=_optional_text(args.get("title")),
        report_json=dict(report_json),
        report_markdown=_optional_text(args.get("report_markdown")),
        quality_score=_optional_float(args.get("quality_score")),
        citation_coverage_score=_optional_float(args.get("citation_coverage_score")),
        manifest_path=_optional_text(args.get("manifest_path")),
    )
    repository.save_report(record)
    return {
        "saved": True,
        "tool_name": tool_name,
        "report_id": record.report_id,
        "run_id": record.run_id,
        "status": record.status,
        "title": record.title,
    }


def _update_source_health(
    args: dict[str, Any],
    *,
    repository: PostgresSourceHealthRepository,
) -> dict[str, Any]:
    source_id = _required_text(args.get("source_id"), "source_id")
    last_error = _source_error(args.get("last_error"), source_id=source_id)
    health = SourceHealth(
        source_id=source_id,
        status=_required_text(args.get("status"), "status"),
        consecutive_failures=max(0, int(args.get("consecutive_failures") or 0)),
        success_count_24h=max(0, int(args.get("success_count_24h") or 0)),
        failure_count_24h=max(0, int(args.get("failure_count_24h") or 0)),
        avg_latency_ms_24h=_optional_float(args.get("avg_latency_ms_24h")),
        last_success_at=_optional_datetime(args.get("last_success_at")),
        last_failure_at=_optional_datetime(args.get("last_failure_at")),
        cooldown_until=_optional_datetime(args.get("cooldown_until")),
        last_error=last_error,
    )
    repository.update_source_health(health)
    return {
        "updated": True,
        "source_id": health.source_id,
        "status": health.status.value,
        "consecutive_failures": health.consecutive_failures,
        "success_count_24h": health.success_count_24h,
        "failure_count_24h": health.failure_count_24h,
        "avg_latency_ms_24h": health.avg_latency_ms_24h,
        "has_last_error": health.last_error is not None,
    }


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _source_error(value: Any, *, source_id: str) -> SourceError | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("last_error must be an object")
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("last_error.metadata must be an object")
    kwargs = {
        "source_id": str(value.get("source_id") or source_id),
        "error_type": _required_text(value.get("error_type"), "last_error.error_type"),
        "error_message": _required_text(value.get("error_message"), "last_error.error_message"),
        "url": _optional_text(value.get("url")),
        "metadata": dict(metadata),
    }
    occurred_at = _optional_datetime(value.get("occurred_at"))
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    return SourceError(**kwargs)


def _optional_datetime(value: Any):
    if value is None:
        return None
    from datetime import UTC, datetime

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
