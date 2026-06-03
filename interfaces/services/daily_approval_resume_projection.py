from __future__ import annotations

from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.human_review_resume import (
    enrich_daily_approval_resume_context,
)


def project_daily_approval_resume_context(
    context_payload: dict[str, Any],
    *,
    workflow_step_ids: list[str],
    workflow_buffer_keys: list[str],
) -> dict[str, Any]:
    return enrich_daily_approval_resume_context(
        context_payload,
        workflow_step_ids=workflow_step_ids,
        workflow_buffer_keys=workflow_buffer_keys,
    )


__all__ = ["project_daily_approval_resume_context"]
