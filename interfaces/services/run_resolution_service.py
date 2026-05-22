from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from business.boards.cross_board.daily_intelligence import (
    build_agentic_daily_intelligence_workflow,
    build_daily_intelligence_workflow,
    build_test_agent_loop_registry,
    build_test_agent_loop_workflow,
    build_test_no_llm_registry,
    build_test_no_llm_workflow,
    normalize_profile,
    normalize_workflow_id,
    resolve_approval_resume_workflow as resolve_daily_approval_resume_workflow,
)
from framework.specs import WorkflowSpec
from framework.workflow import FunctionStepRegistry


@dataclass(frozen=True)
class ResolvedWorkflow:
    workflow: WorkflowSpec
    profile: str
    registry: FunctionStepRegistry


class ApprovalResumeWorkflowResolver(Protocol):
    def __call__(self, workflow_id: str, *, profile: str | None) -> ResolvedWorkflow:
        ...


class RunResolutionApplicationService:
    def __init__(self, resolver: ApprovalResumeWorkflowResolver | None = None) -> None:
        self._resolver = resolver or resolve_approval_resume_workflow

    def resolve_approval_resume_workflow(
        self,
        workflow_id: str,
        *,
        profile: str | None,
    ) -> ResolvedWorkflow:
        if self._resolver is None:
            raise RuntimeError("approval resume workflow resolver is not configured")
        return self._resolver(workflow_id, profile=profile)


def resolve_approval_resume_workflow(
    workflow_id: str,
    *,
    profile: str | None,
) -> ResolvedWorkflow:
    resolved = resolve_daily_approval_resume_workflow(workflow_id, profile=profile)
    return ResolvedWorkflow(
        workflow=resolved.workflow,
        profile=resolved.profile,
        registry=resolved.registry,
    )


_ResolvedWorkflow = ResolvedWorkflow
_normalize_profile = normalize_profile
_normalize_workflow_id = normalize_workflow_id
_resolve_approval_resume_workflow = resolve_approval_resume_workflow


def __getattr__(name: str) -> Any:
    if name in {
        "build_agentic_daily_intelligence_workflow",
        "build_daily_intelligence_workflow",
        "build_test_agent_loop_registry",
        "build_test_agent_loop_workflow",
        "build_test_no_llm_registry",
        "build_test_no_llm_workflow",
    }:
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ResolvedWorkflow",
    "RunResolutionApplicationService",
    "_ResolvedWorkflow",
    "_normalize_profile",
    "_normalize_workflow_id",
    "_resolve_approval_resume_workflow",
    "build_agentic_daily_intelligence_workflow",
    "build_daily_intelligence_workflow",
    "build_test_agent_loop_registry",
    "build_test_agent_loop_workflow",
    "build_test_no_llm_registry",
    "build_test_no_llm_workflow",
    "normalize_profile",
    "normalize_workflow_id",
    "resolve_approval_resume_workflow",
]
