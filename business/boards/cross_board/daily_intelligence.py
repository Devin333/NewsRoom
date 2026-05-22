from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from business.boards.cross_board.profiles import (
    AGENTIC_DAILY_WORKFLOW_ID,
    LEGACY_DAILY_WORKFLOW_ID,
    PROFILE_AGENTIC_LIVE,
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
    daily_agentic_enabled,
)
from business.boards.cross_board.workflows.daily_intelligence import (
    AgenticDailyIntelligenceRunner,
    DailyIntelligenceRunner,
    build_agentic_daily_intelligence_workflow,
    build_daily_intelligence_workflow,
    build_test_agent_loop_registry,
    build_test_agent_loop_workflow,
    build_test_no_llm_registry,
    build_test_no_llm_workflow,
    run_test_agent_loop,
    run_test_no_llm,
)
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
    build_daily_intelligence_artifact_publishers,
)
from business.layers.relation.lineage import evidence_bundle_lineage_extractor
from business.layers.signal.indexing import source_artifact_ref_extractor
from framework.specs import WorkflowSpec
from framework.workflow import FunctionStepRegistry


@dataclass(frozen=True)
class ResolvedDailyWorkflow:
    workflow: WorkflowSpec
    profile: str
    registry: FunctionStepRegistry


def resolve_daily_runner_cls(profile: str):
    if profile in {PROFILE_LIVE, PROFILE_LIVE_OFFLINE}:
        return AgenticDailyIntelligenceRunner
    return AgenticDailyIntelligenceRunner if daily_agentic_enabled(profile) else DailyIntelligenceRunner


def resolve_approval_resume_workflow(
    workflow_id: str,
    *,
    profile: str | None,
) -> ResolvedDailyWorkflow:
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
        return ResolvedDailyWorkflow(
            workflow=build_agentic_daily_intelligence_workflow(actual_profile),
            profile=actual_profile,
            registry=runner._function_registry(actual_profile),
        )
    if normalized_workflow in {"test-no-llm", "daily-intelligence-test-no-llm"}:
        if normalized_profile and normalized_profile != "test-no-llm":
            raise ValueError(f"unsupported test-no-llm approval resume profile: {normalized_profile}")
        return ResolvedDailyWorkflow(
            workflow=build_test_no_llm_workflow(),
            profile="test-no-llm",
            registry=build_test_no_llm_registry(),
        )
    if normalized_workflow in {"test-agent-loop", "daily-intelligence-test-agent-loop"}:
        if normalized_profile and normalized_profile != "test-agent-loop":
            raise ValueError(f"unsupported test-agent-loop approval resume profile: {normalized_profile}")
        return ResolvedDailyWorkflow(
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


def daily_artifact_ref_extractors() -> list[Callable]:
    return [source_artifact_ref_extractor]


def daily_lineage_extractors() -> list[Callable]:
    return [evidence_bundle_lineage_extractor]


__all__ = [
    "AgenticDailyIntelligenceRunner",
    "DailyIntelligenceRunner",
    "ResolvedDailyWorkflow",
    "build_agentic_daily_intelligence_workflow",
    "build_daily_intelligence_workflow",
    "build_daily_intelligence_artifact_publishers",
    "build_test_agent_loop_registry",
    "build_test_agent_loop_workflow",
    "build_test_no_llm_registry",
    "build_test_no_llm_workflow",
    "daily_artifact_ref_extractors",
    "daily_lineage_extractors",
    "normalize_profile",
    "normalize_workflow_id",
    "resolve_approval_resume_workflow",
    "resolve_daily_runner_cls",
    "run_test_agent_loop",
    "run_test_no_llm",
]
