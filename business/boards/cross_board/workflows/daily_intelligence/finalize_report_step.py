from __future__ import annotations

from typing import Any

from framework.workflow import DataBufferReadPermissionError, StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.report_finalization import (
    DailyReportFinalizationInput,
    finalize_daily_report,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_list,
)


def finalize_report(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    """Workflow adapter for agentic Daily report finalization."""

    return finalize_daily_report(
        DailyReportFinalizationInput(
            request=buffer.read("request"),
            report_draft=buffer.read("report_draft"),
            editor_review=buffer.read("editor_review"),
            verification_result=buffer.read("verification_result"),
            citation_check_result=buffer.read("citation_check_result"),
            support_matrix=buffer.read("support_matrix"),
            evidence_bundle=buffer.read("evidence_bundle"),
            verified_findings=buffer.read("verified_findings"),
            quality_events=read_buffer_list(buffer, "quality_events"),
            edited_report_draft=_read_optional_value(buffer, "edited_report_draft"),
            agent_feedback_events=_read_optional_buffer_list(buffer, "agent_feedback_events"),
            agent_feedback_summary=_read_optional_value(buffer, "agent_feedback_summary"),
        )
    )


def _read_optional_buffer_list(buffer: StepScopedDataBufferView, key: str) -> list[Any]:
    try:
        if not buffer.exists(key):
            return []
        return read_buffer_list(buffer, key)
    except DataBufferReadPermissionError:
        return []


def _read_optional_value(buffer: StepScopedDataBufferView, key: str) -> Any | None:
    try:
        if not buffer.exists(key):
            return None
        return buffer.read(key, required=False)
    except DataBufferReadPermissionError:
        return None
