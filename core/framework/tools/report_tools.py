from __future__ import annotations

import re
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.reports import FinalReport, render_markdown


def register_report_tools(
    registry: ToolRegistry,
    *,
    artifact_manager: ArtifactManager | None = None,
    run_id: str | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="report.render_markdown",
            description="Render a FinalReport payload to markdown.",
            input_schema={
                "required": ["report"],
                "properties": {"report": {"type": "object"}},
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: {"markdown": render_markdown(_final_report(args["report"]))},
    )
    registry.register(
        ToolDefinition(
            name="report.render_json",
            description="Normalize a FinalReport payload to JSON.",
            input_schema={
                "required": ["report"],
                "properties": {"report": {"type": "object"}},
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: {"report": _final_report(args["report"]).to_dict()},
    )
    registry.register(
        ToolDefinition(
            name="report.validate",
            description="Validate a FinalReport payload without rendering it.",
            input_schema={
                "required": ["report"],
                "properties": {"report": {"type": "object"}},
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: _validate_report(args["report"]),
    )
    if artifact_manager is not None and run_id is not None:
        registry.register(
            ToolDefinition(
                name="report.export",
                description="Export a FinalReport payload to a run artifact.",
                input_schema={
                    "required": ["report"],
                    "properties": {
                        "report": {"type": "object"},
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "json"],
                        },
                        "path": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_local_state",
            ),
            lambda args: _export_report(
                args,
                artifact_manager=artifact_manager,
                run_id=run_id,
            ),
        )


def _validate_report(payload: Any) -> dict[str, Any]:
    try:
        report = _final_report(payload)
    except Exception as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "section_count": 0,
            "source_url_count": 0,
        }
    return {
        "valid": True,
        "errors": [],
        "section_count": len(report.sections),
        "source_url_count": len(report.source_urls),
    }


def _export_report(
    args: dict[str, Any],
    *,
    artifact_manager: ArtifactManager,
    run_id: str,
) -> dict[str, Any]:
    report = _final_report(args["report"])
    export_format = str(args.get("format") or "markdown")
    relative_path = str(args.get("path") or _default_export_path(report, export_format))
    if export_format == "json":
        target = artifact_manager.write_json(run_id, relative_path, report.to_dict())
        content_type = "application/json"
    elif export_format == "markdown":
        target = artifact_manager.write_text(run_id, relative_path, render_markdown(report))
        content_type = "text/markdown"
    else:
        raise ValueError(f"unsupported report export format: {export_format}")
    return {
        "artifact_id": f"report:{relative_path}",
        "relative_path": relative_path,
        "format": export_format,
        "content_type": content_type,
        "size_bytes": target.stat().st_size,
    }


def _default_export_path(report: FinalReport, export_format: str) -> str:
    extension = "json" if export_format == "json" else "md"
    slug = re.sub(r"[^a-z0-9]+", "-", report.title.casefold()).strip("-")
    if not slug:
        slug = "report"
    return f"reports/{slug}.{extension}"


def _final_report(payload: Any) -> FinalReport:
    if not isinstance(payload, dict):
        raise ValueError("report must be an object")
    title = str(payload.get("title") or "")
    if not title:
        raise ValueError("report.title is required")
    sections = payload.get("sections") or []
    if not isinstance(sections, list):
        raise ValueError("report.sections must be a list")
    source_urls = payload.get("source_urls") or []
    if not isinstance(source_urls, list):
        raise ValueError("report.source_urls must be a list")
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("report.metadata must be an object")
    return FinalReport(
        title=title,
        sections=[dict(section) for section in sections],
        source_urls=[str(url) for url in source_urls],
        metadata=dict(metadata),
    )
