from __future__ import annotations

from framework.tool import ToolRegistry
from framework.tool.models import ToolDefinition
from business.boards.cross_board.workflows.daily_intelligence.agent_tool_service import (
    DailyAgentToolService,
)


def build_daily_agent_tool_registry(
    *,
    service: DailyAgentToolService | None = None,
) -> ToolRegistry:
    tool_service = service or DailyAgentToolService()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="daily.evidence_search",
            description="Search the provided daily evidence bundle without leaving the source boundary.",
            input_schema={
                "type": "object",
                "required": ["evidence_bundle"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "query": {"type": "string"},
                    "evidence_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "source_url": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=100_000,
        ),
        tool_service.search_evidence,
    )
    registry.register(
        ToolDefinition(
            name="daily.source_metadata",
            description="Summarize source metadata from the provided daily evidence bundle.",
            input_schema={
                "type": "object",
                "required": ["evidence_bundle"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "source_id": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=100_000,
        ),
        tool_service.source_metadata,
    )
    registry.register(
        ToolDefinition(
            name="daily.citation_validate",
            description="Validate report citations against the provided daily evidence bundle.",
            input_schema={
                "type": "object",
                "required": ["report", "evidence_bundle"],
                "properties": {
                    "report": {"type": "object"},
                    "evidence_bundle": {"type": "object"},
                    "verified_findings": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=200_000,
        ),
        tool_service.validate_citations,
    )
    registry.register(
        ToolDefinition(
            name="daily.section_draft",
            description=(
                "Build a source-bounded report section skeleton from the provided daily "
                "evidence bundle."
            ),
            input_schema={
                "type": "object",
                "required": ["evidence_bundle", "title"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "title": {"type": "string"},
                    "section_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=120_000,
        ),
        tool_service.build_section_draft,
    )
    return registry


__all__ = ["build_daily_agent_tool_registry"]
