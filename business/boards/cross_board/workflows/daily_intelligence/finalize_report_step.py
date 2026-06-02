from __future__ import annotations

from typing import Any

from framework.workflow import StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.report_finalization import (
    DailyReportFinalizationInput,
    finalize_daily_report,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_buffer_access import (
    read_buffer_list,
    read_buffer_value,
    read_optional_buffer_list,
    read_optional_buffer_value,
)


def finalize_report(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    """Workflow adapter for agentic Daily report finalization."""

    return finalize_daily_report(
        DailyReportFinalizationInput(
            request=read_buffer_value(buffer, "request"),
            report_draft=read_buffer_value(buffer, "report_draft"),
            editor_review=_editor_review_or_feedback_block(buffer),
            verification_result=read_buffer_value(buffer, "verification_result"),
            citation_check_result=read_buffer_value(buffer, "citation_check_result"),
            support_matrix=read_buffer_value(buffer, "support_matrix"),
            evidence_bundle=read_buffer_value(buffer, "evidence_bundle"),
            verified_findings=read_buffer_value(buffer, "verified_findings"),
            quality_events=read_buffer_list(buffer, "quality_events"),
            edited_report_draft=read_optional_buffer_value(buffer, "edited_report_draft"),
            agent_feedback_events=read_optional_buffer_list(buffer, "agent_feedback_events"),
            agent_feedback_summary=read_optional_buffer_value(buffer, "agent_feedback_summary"),
        )
    )


def _editor_review_or_feedback_block(buffer: StepScopedDataBufferView) -> Any:
    editor_review = read_optional_buffer_value(buffer, "editor_review")
    if editor_review is not None:
        return editor_review
    route = read_optional_buffer_value(buffer, "agent_feedback_route")
    reason = "agent feedback blocked publication before editor review"
    if isinstance(route, dict):
        reason = str(route.get("reason") or reason)
    return {
        "decision": "blocked",
        "quality_score": 0.0,
        "reasons": [reason],
        "rewrite_instructions": [],
    }
