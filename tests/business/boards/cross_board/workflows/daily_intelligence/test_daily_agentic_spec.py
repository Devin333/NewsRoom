from __future__ import annotations

from framework.specs import StepType
from framework.workflow import FunctionStepRegistry, WorkflowCompiler
from framework.workflow.runners.step_runner import build_default_step_runner_registry
from business.boards.cross_board.workflows.daily_intelligence import build_agentic_daily_intelligence_workflow
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    PROFILE_AGENTIC_OFFLINE,
    build_daily_agent_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_runner_factory import (
    build_profiled_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    ANALYST_AGENT_ID,
    EDITOR_AGENT_ID,
    PLANNER_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
)
from business.boards.cross_board.workflows.daily_intelligence.source_evidence_steps import (
    build_source_and_evidence_steps,
)


def test_agentic_daily_workflow_start_and_terminal_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)

    assert workflow.start_step_id == "collect_sources"
    assert workflow.terminal_step_ids == ["finalize_report"]
    assert workflow.workflow_id == "daily-intelligence-agentic"


def test_agentic_daily_workflow_declares_agent_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    steps = {step.step_id: step for step in workflow.steps}

    assert steps["planner_agent"].step_type == StepType.AGENT_LOOP
    assert steps["planner_agent"].metadata["agent_id"] == PLANNER_AGENT_ID
    assert steps["planner_agent"].implementation == PLANNER_AGENT_ID

    assert steps["analyst_agent"].step_type == StepType.AGENT_LOOP
    assert steps["analyst_agent"].metadata["agent_id"] == ANALYST_AGENT_ID
    assert steps["analyst_agent"].implementation == ANALYST_AGENT_ID

    assert steps["writer_agent"].step_type == StepType.AGENT_LOOP
    assert steps["writer_agent"].metadata["agent_id"] == WRITER_AGENT_ID
    assert steps["writer_agent"].implementation == WRITER_AGENT_ID

    assert steps["verifier_agent"].step_type == StepType.AGENT_LOOP
    assert steps["verifier_agent"].metadata["agent_id"] == VERIFIER_AGENT_ID
    assert steps["verifier_agent"].implementation == VERIFIER_AGENT_ID

    assert steps["editor_agent"].step_type == StepType.AGENT_LOOP
    assert steps["editor_agent"].metadata["agent_id"] == EDITOR_AGENT_ID
    assert steps["editor_agent"].implementation == EDITOR_AGENT_ID

    assert steps["collect_agent_feedback"].step_type == StepType.FUNCTION
    assert steps["collect_agent_feedback"].implementation == "daily.collect_agent_feedback"
    assert steps["collect_agent_feedback"].required_output_keys == ["agent_feedback_summary"]
    assert "agent.feedback.summary" in steps["collect_agent_feedback"].write_keys
    assert "agent.feedback.events" in steps["collect_agent_feedback"].write_keys
    assert "agent_feedback_events" in steps["finalize_report"].read_keys
    assert "quality.result" in steps["finalize_report"].write_keys


def test_agentic_daily_workflow_reuses_source_evidence_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)

    assert _step_signatures(workflow.steps[:6]) == _step_signatures(
        build_source_and_evidence_steps()
    )


def test_agentic_daily_workflow_routes_evidence_to_agents_to_finalize() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    edges = {
        edge.edge_id: (edge.source_step_id, edge.target_step_id)
        for edge in workflow.edges
    }

    assert edges["evidence-to-planner"] == ("build_evidence", "planner_agent")
    assert edges["planner-to-analyst"] == ("planner_agent", "analyst_agent")
    assert edges["analyst-to-writer"] == ("analyst_agent", "writer_agent")
    assert edges["writer-to-verifier"] == ("writer_agent", "verifier_agent")
    assert edges["verifier-to-editor"] == ("verifier_agent", "editor_agent")
    assert edges["editor-to-feedback"] == ("editor_agent", "collect_agent_feedback")
    assert edges["feedback-to-finalize"] == ("collect_agent_feedback", "finalize_report")


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
        "daily.collect_agent_feedback",
        "daily.finalize_report",
    ]:
        function_registry.register(implementation, lambda buffer: {})

    return build_default_step_runner_registry(
        function_registry,
        tool_registry=build_daily_agent_tool_registry(),
        agent_runner=build_profiled_daily_agent_runner(profile=PROFILE_AGENTIC_OFFLINE),
        agent_registry=build_daily_agent_registry(),
    )


def _step_signatures(steps) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
    return [
        (
            step.step_id,
            step.implementation,
            tuple(step.read_keys),
            tuple(step.write_keys),
            tuple(step.required_output_keys),
        )
        for step in steps
    ]
