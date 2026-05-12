from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from domain.reports import FinalReport, render_markdown


def register_report_tools(registry: ToolRegistry) -> None:
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
