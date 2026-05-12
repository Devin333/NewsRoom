from __future__ import annotations

from typing import Any, Protocol

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from storage.repository import ReportRecord


class PostgresReportRepository(Protocol):
    def save_report(self, record: ReportRecord) -> None: ...


def register_postgres_tools(
    registry: ToolRegistry,
    *,
    repository: PostgresReportRepository,
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
