from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from framework.specs import WorkflowSpec
from framework.workflow import FunctionStepRegistry


@dataclass(frozen=True)
class ResolvedWorkflow:
    workflow: WorkflowSpec
    profile: str
    registry: FunctionStepRegistry


class RunResolutionApplicationService:
    def __init__(self, resolver: Callable[[str], ResolvedWorkflow] | None = None) -> None:
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
    from business.boards.cross_board.profiles import (
        AGENTIC_DAILY_WORKFLOW_ID,
        LEGACY_DAILY_WORKFLOW_ID,
        PROFILE_AGENTIC_LIVE,
        PROFILE_AGENTIC_OFFLINE,
        PROFILE_LIVE,
        PROFILE_LIVE_OFFLINE,
    )
    from business.boards.cross_board.workflows.daily_intelligence import (
        AgenticDailyIntelligenceRunner,
        build_agentic_daily_intelligence_workflow,
        build_test_agent_loop_registry,
        build_test_agent_loop_workflow,
        build_test_no_llm_registry,
        build_test_no_llm_workflow,
    )

    normalized_workflow = normalize_workflow_id(workflow_id)
    normalized_profile = normalize_profile(profile)
    if normalized_workflow in {
        "daily",
        "daily-intelligence",
        "daily_intelligence",
        LEGACY_DAILY_WORKFLOW_ID,
        AGENTIC_DAILY_WORKFLOW_ID,
    }:
        actual_profile = normalized_profile or PROFILE_AGENTIC_LIVE
        if actual_profile == PROFILE_LIVE:
            actual_profile = PROFILE_AGENTIC_LIVE
        if actual_profile == PROFILE_LIVE_OFFLINE:
            actual_profile = PROFILE_AGENTIC_OFFLINE
        if actual_profile not in {PROFILE_AGENTIC_LIVE, PROFILE_AGENTIC_OFFLINE}:
            raise ValueError(f"unsupported daily approval resume profile: {actual_profile}")
        runner = AgenticDailyIntelligenceRunner()
        return ResolvedWorkflow(
            workflow=build_agentic_daily_intelligence_workflow(actual_profile),
            profile=actual_profile,
            registry=runner._function_registry(actual_profile),
        )
    if normalized_workflow in {"test-no-llm", "daily-intelligence-test-no-llm"}:
        if normalized_profile and normalized_profile != "test-no-llm":
            raise ValueError(f"unsupported test-no-llm approval resume profile: {normalized_profile}")
        return ResolvedWorkflow(
            workflow=build_test_no_llm_workflow(),
            profile="test-no-llm",
            registry=build_test_no_llm_registry(),
        )
    if normalized_workflow in {"test-agent-loop", "daily-intelligence-test-agent-loop"}:
        if normalized_profile and normalized_profile != "test-agent-loop":
            raise ValueError(f"unsupported test-agent-loop approval resume profile: {normalized_profile}")
        return ResolvedWorkflow(
            workflow=build_test_agent_loop_workflow(),
            profile="test-agent-loop",
            registry=build_test_agent_loop_registry(),
        )
    raise ValueError(f"unsupported approval resume workflow_id: {workflow_id}")


def normalize_workflow_id(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError("workflow_id is required")
    return normalized


def normalize_profile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


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
        from business.boards.cross_board.workflows import daily_intelligence

        return getattr(daily_intelligence, name)
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
