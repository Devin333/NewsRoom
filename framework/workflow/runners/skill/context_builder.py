from __future__ import annotations

from typing import Any

from framework.workflow.runners.skill.accessors import (
    retry,
    skill_name,
    step_id,
    timeout_seconds,
    trace_id,
    workflow_run_id,
)
from framework.workflow.runners.skill.context import SkillRunContext


def build_skill_run_context(
    step: Any,
    buffer: Any,
    *,
    configured_run_id: str | None,
    trace_context: Any,
) -> SkillRunContext:
    resolved_step_id = step_id(step)
    resolved_skill_name = skill_name(step)
    resolved_workflow_run_id = workflow_run_id(buffer, configured_run_id)
    context = SkillRunContext.for_workflow(
        skill_name=resolved_skill_name,
        workflow_run_id=resolved_workflow_run_id,
        step_id=resolved_step_id,
    )
    resolved_trace_id = trace_id(buffer, trace_context)
    if resolved_trace_id is not None:
        context.trace_id = resolved_trace_id
    resolved_timeout_seconds = timeout_seconds(step)
    if resolved_timeout_seconds is not None:
        context.timeout_seconds = resolved_timeout_seconds
    retry_spec = retry(step)
    if isinstance(retry_spec, dict):
        max_retries = retry_spec.get("max_retries") or retry_spec.get("max_attempts")
        if max_retries is not None:
            context.max_retries = int(max_retries)
    context.metadata.update(
        {
            "workflow_step_id": resolved_step_id,
            "workflow_step_type": "skill",
        }
    )
    return context


__all__ = [
    "build_skill_run_context",
]
