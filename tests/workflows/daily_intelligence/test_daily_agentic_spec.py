from __future__ import annotations

from core.framework.specs import StepType
from core.framework.workflow import FunctionStepRegistry, WorkflowCompiler
from core.framework.workflow.step_runner import build_default_step_runner_registry
from workflows.daily_intelligence import build_agentic_daily_intelligence_workflow
from workflows.daily_intelligence.agent_registry import (
    PROFILE_AGENTIC_OFFLINE,
    build_daily_agent_registry,
    build_daily_agent_runner,
)
from workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from workflows.daily_intelligence.agents import (
    EDITOR_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)


def test_agentic_daily_workflow_start_and_terminal_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)

    assert workflow.start_step_id == "collect_sources"
    assert workflow.terminal_step_ids == ["finalize_report"]
    assert workflow.workflow_id == "daily-intelligence-agentic"


def test_agentic_daily_workflow_declares_agent_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    steps = {step.step_id: step for step in workflow.steps}

    assert steps["writer_agent"].step_type == StepType.AGENT_LOOP
    assert steps["writer_agent"].metadata["agent_id"] == WRITER_AGENT_ID
    assert steps["writer_agent"].implementation == WRITER_AGENT_ID

    assert steps["verifier_agent"].step_type == StepType.AGENT_LOOP
    assert steps["verifier_agent"].metadata["agent_id"] == VERIFIER_AGENT_ID
    assert steps["verifier_agent"].implementation == VERIFIER_AGENT_ID

    assert steps["editor_agent"].step_type == StepType.AGENT_LOOP
    assert steps["editor_agent"].metadata["agent_id"] == EDITOR_AGENT_ID
    assert steps["editor_agent"].implementation == EDITOR_AGENT_ID


def test_agentic_daily_workflow_routes_evidence_to_agents_to_finalize() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    edges = {
        edge.edge_id: (edge.source_step_id, edge.target_step_id)
        for edge in workflow.edges
    }

    assert edges["evidence-to-writer"] == ("build_evidence", "writer_agent")
    assert edges["writer-to-verifier"] == ("writer_agent", "verifier_agent")
    assert edges["verifier-to-editor"] == ("verifier_agent", "editor_agent")
    assert edges["editor-to-finalize"] == ("editor_agent", "finalize_report")


def test_agentic_daily_workflow_compile_passes_with_runner_registry() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    registry = _step_runner_registry()

    result = WorkflowCompiler(runner_registry=registry).compile(workflow)

    assert result.passed is True
    assert set(result.required_step_types) == {StepType.FUNCTION, StepType.AGENT_LOOP}


def test_agentic_daily_workflow_step_runner_validation_passes() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    registry = _step_runner_registry()

    result = registry.validate_workflow(workflow)

    assert result.passed is True
    assert result.errors == []


def _step_runner_registry():
    function_registry = FunctionStepRegistry()
    for implementation in [
        "daily.collect_sources",
        "daily.require_sources",
        "daily.normalize_sources",
        "daily.deduplicate_sources",
        "daily.rank_sources",
        "daily.build_evidence",
        "daily.finalize_report",
    ]:
        function_registry.register(implementation, lambda buffer: {})

    return build_default_step_runner_registry(
        function_registry,
        tool_registry=build_daily_agent_tool_registry(),
        agent_runner=build_daily_agent_runner(profile=PROFILE_AGENTIC_OFFLINE),
        agent_registry=build_daily_agent_registry(),
    )
