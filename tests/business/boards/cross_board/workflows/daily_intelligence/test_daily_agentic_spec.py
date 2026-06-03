from __future__ import annotations

from framework.specs import EdgeCondition, StepType
from framework.workflow import FunctionStepRegistry, WorkflowCompiler
from framework.workflow.runners.step_runner import build_default_step_runner_registry
from framework.workflow.runtime.timeout import workflow_timeout_budget
from business.boards.cross_board.workflows.daily_intelligence import (
    build_agentic_daily_intelligence_workflow,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    PROFILE_AGENTIC_OFFLINE,
    build_daily_agent_registry,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_runner_factory import (
    build_profiled_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import (
    build_daily_agent_tool_registry,
)
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
from business.boards.cross_board.workflows.daily_intelligence.workflow_runtime_policy import (
    DAILY_WORKFLOW_TIMEOUT_SECONDS,
)


def test_agentic_daily_workflow_start_and_terminal_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)

    assert workflow.start_step_id == "collect_sources"
    assert workflow.terminal_step_ids == ["finalize_report"]
    assert workflow.workflow_id == "daily-intelligence-agentic"


def test_agentic_daily_workflow_declares_global_timeout_budget() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    budget = workflow_timeout_budget(workflow, started_monotonic=10.0)

    assert (
        workflow.policies.timeout_policy.timeout_seconds
        == DAILY_WORKFLOW_TIMEOUT_SECONDS
    )
    assert budget is not None
    assert budget.timeout_seconds == DAILY_WORKFLOW_TIMEOUT_SECONDS
    assert budget.policy_source == "policies.timeout_policy.timeout_seconds"


def test_agentic_daily_workflow_declares_agent_steps() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    steps = {step.step_id: step for step in workflow.steps}

    assert steps["planner_agent"].step_type == StepType.AGENT_LOOP
    assert steps["planner_agent"].metadata["agent_id"] == PLANNER_AGENT_ID
    assert steps["planner_agent"].implementation == PLANNER_AGENT_ID
    assert steps["planner_agent"].read_keys == [
        "request",
        "evidence.bundle",
        "evidence_bundle",
        "sources.errors",
        "source_errors",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    planner_optional_reads = steps["planner_agent"].metadata["optional_read_keys"]
    assert "agent_feedback_summary" in planner_optional_reads
    assert "agent.feedback.summary" in planner_optional_reads
    assert "agent_feedback_route" in planner_optional_reads
    assert "agent.feedback.route" in planner_optional_reads
    assert "source_recollection_profile" in planner_optional_reads
    assert "sources.recollection_profile" in planner_optional_reads
    assert "source_recollection_execution_plan" in planner_optional_reads
    assert "sources.recollection_execution_plan" in planner_optional_reads
    assert "source_recollection_execution_report" in planner_optional_reads
    assert "sources.recollection_execution_report" in planner_optional_reads
    assert "source_recollection_quality_assessment" in planner_optional_reads
    assert "sources.recollection_quality_assessment" in planner_optional_reads

    assert steps["analyst_agent"].step_type == StepType.AGENT_LOOP
    assert steps["analyst_agent"].metadata["agent_id"] == ANALYST_AGENT_ID
    assert steps["analyst_agent"].implementation == ANALYST_AGENT_ID
    assert steps["analyst_agent"].read_keys == [
        "request",
        "agent.planner.research_plan",
        "research_plan",
        "evidence.bundle",
        "evidence_bundle",
        "sources.errors",
        "source_errors",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert "agent.planner.research_plan" in steps["planner_agent"].write_keys
    assert "agent.planner.notes" in steps["planner_agent"].write_keys

    assert steps["writer_agent"].step_type == StepType.AGENT_LOOP
    assert steps["writer_agent"].metadata["agent_id"] == WRITER_AGENT_ID
    assert steps["writer_agent"].implementation == WRITER_AGENT_ID
    assert steps["writer_agent"].read_keys == [
        "request",
        "agent.planner.research_plan",
        "research_plan",
        "agent.analyst.analysis_result",
        "analysis_result",
        "evidence.verified_findings",
        "verified_findings",
        "evidence.bundle",
        "evidence_bundle",
        "sources.errors",
        "source_errors",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert "report.draft" in steps["writer_agent"].write_keys
    assert "agent.writer.notes" in steps["writer_agent"].write_keys
    assert "agent.analyst.analysis_result" in steps["analyst_agent"].write_keys
    assert "agent.analyst.notes" in steps["analyst_agent"].write_keys
    assert steps["writer_agent"].metadata["optional_read_keys"] == [
        "quality.citation_check_result",
        "citation_check_result",
        "quality.support_matrix",
        "support_matrix",
        "quality.verification_result",
        "verification_result",
        "agent.feedback.events",
        "agent_feedback_events",
        "agent.feedback.summary",
        "agent_feedback_summary",
        "agent.feedback.route",
        "agent_feedback_route",
        "agent.feedback.loop_state",
        "agent_feedback_loop_state",
    ]

    assert steps["verifier_agent"].step_type == StepType.AGENT_LOOP
    assert steps["verifier_agent"].metadata["agent_id"] == VERIFIER_AGENT_ID
    assert steps["verifier_agent"].implementation == VERIFIER_AGENT_ID
    assert steps["verifier_agent"].read_keys == [
        "report.draft",
        "report_draft",
        "evidence.bundle",
        "evidence_bundle",
        "evidence.candidate_claims",
        "candidate_claims",
        "evidence.verified_findings",
        "verified_findings",
    ]
    assert "quality.verification_result" in steps["verifier_agent"].write_keys
    assert "quality.citation_check_result" in steps["verifier_agent"].write_keys
    assert "quality.support_matrix" in steps["verifier_agent"].write_keys
    assert "agent.verifier.notes" in steps["verifier_agent"].write_keys

    assert steps["editor_agent"].step_type == StepType.AGENT_LOOP
    assert steps["editor_agent"].metadata["agent_id"] == EDITOR_AGENT_ID
    assert steps["editor_agent"].implementation == EDITOR_AGENT_ID
    assert steps["editor_agent"].read_keys == [
        "report.draft",
        "report_draft",
        "quality.verification_result",
        "verification_result",
        "quality.citation_check_result",
        "citation_check_result",
        "quality.support_matrix",
        "support_matrix",
        "evidence.bundle",
        "evidence_bundle",
    ]
    assert "quality.editor_review" in steps["editor_agent"].write_keys
    assert "report.edited_draft" in steps["editor_agent"].write_keys
    assert "agent.editor.notes" in steps["editor_agent"].write_keys

    assert steps["collect_agent_feedback"].step_type == StepType.FUNCTION
    assert steps["collect_agent_feedback"].implementation == "daily.collect_agent_feedback"
    assert steps["collect_agent_feedback"].required_output_keys == ["agent_feedback_summary"]
    assert steps["collect_agent_feedback"].read_keys == [
        "agent.analyst.analysis_result",
        "analysis_result",
        "quality.verification_result",
        "verification_result",
        "quality.citation_check_result",
        "citation_check_result",
        "quality.support_matrix",
        "support_matrix",
    ]
    assert steps["collect_agent_feedback"].metadata["optional_read_keys"] == [
        "quality.editor_review",
        "editor_review",
        "agent.feedback.loop_state",
        "agent_feedback_loop_state",
    ]
    assert "agent.feedback.summary" in steps["collect_agent_feedback"].write_keys
    assert "agent.feedback.events" in steps["collect_agent_feedback"].write_keys
    assert "agent.feedback.route" in steps["collect_agent_feedback"].write_keys
    assert "agent.feedback.loop_state" in steps["collect_agent_feedback"].write_keys
    assert "source_recollection_profile" in steps["collect_agent_feedback"].write_keys
    assert "sources.recollection_profile" in steps["collect_agent_feedback"].write_keys
    assert "source_recollection_execution_plan" in steps["collect_agent_feedback"].write_keys
    assert "sources.recollection_execution_plan" in steps["collect_agent_feedback"].write_keys
    assert steps["recollect_sources"].step_type == StepType.FUNCTION
    assert steps["recollect_sources"].implementation == "daily.recollect_sources"
    assert steps["recollect_sources"].read_keys == [
        "request",
        "sources.recollection_execution_plan",
        "source_recollection_execution_plan",
    ]
    assert steps["recollect_sources"].metadata["optional_read_keys"] == [
        "sources.raw_items",
        "raw_items",
        "sources.errors",
        "source_errors",
        "sources.skipped",
        "skipped_sources",
        "sources.failed",
        "failed_sources",
        "sources.fetch_requests",
        "source_fetch_requests",
        "sources.fetch_results",
        "source_fetch_results",
        "sources.health_updates",
        "source_health_updates",
        "sources.events",
        "source_events",
        "sources.pipeline_metrics",
        "source_pipeline_metrics",
    ]
    assert "sources.fetch_requests" in steps["recollect_sources"].write_keys
    assert "sources.fetch_results" in steps["recollect_sources"].write_keys
    assert "source_recollection_execution_report" in steps["recollect_sources"].write_keys
    assert "sources.recollection_execution_report" in steps["recollect_sources"].write_keys
    assert "source_recollection_execution_report" in steps["recollect_sources"].required_output_keys
    assert "source_recollection_quality_assessment" in steps["recollect_sources"].write_keys
    assert "sources.recollection_quality_assessment" in steps["recollect_sources"].write_keys
    assert (
        "source_recollection_quality_assessment"
        in steps["recollect_sources"].required_output_keys
    )
    assert steps["finalize_report"].read_keys == [
        "request",
        "report.draft",
        "report_draft",
        "quality.verification_result",
        "verification_result",
        "quality.citation_check_result",
        "citation_check_result",
        "quality.support_matrix",
        "support_matrix",
        "evidence.bundle",
        "evidence_bundle",
        "evidence.verified_findings",
        "verified_findings",
        "quality.events",
        "quality_events",
        "agent.feedback.events",
        "agent_feedback_events",
        "agent.feedback.summary",
        "agent_feedback_summary",
        "agent.feedback.route",
        "agent_feedback_route",
    ]
    assert steps["finalize_report"].metadata["optional_read_keys"] == [
        "report.edited_draft",
        "edited_report_draft",
        "quality.editor_review",
        "editor_review",
        "sources.recollection_quality_assessment",
        "source_recollection_quality_assessment",
    ]
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
    assert edges["verifier-to-feedback"] == ("verifier_agent", "collect_agent_feedback")
    assert edges["editor-to-feedback"] == ("editor_agent", "collect_agent_feedback")
    assert edges["feedback-recollect-to-sources"] == ("collect_agent_feedback", "recollect_sources")
    assert edges["recollect-to-normalize"] == ("recollect_sources", "normalize_sources")
    assert edges["feedback-retry-to-writer"] == ("collect_agent_feedback", "writer_agent")
    assert edges["feedback-pass-to-editor"] == ("collect_agent_feedback", "editor_agent")
    assert edges["feedback-to-finalize"] == ("collect_agent_feedback", "finalize_report")


def test_agentic_daily_workflow_declares_bounded_feedback_routes() -> None:
    workflow = build_agentic_daily_intelligence_workflow(PROFILE_AGENTIC_OFFLINE)
    edges = {edge.edge_id: edge for edge in workflow.edges}

    assert edges["verifier-to-feedback"].condition == EdgeCondition.ON_SUCCESS
    assert edges["feedback-recollect-to-sources"].condition == EdgeCondition.CONDITIONAL
    assert edges["feedback-recollect-to-sources"].condition_expr == (
        "outcome.outputs.agent_feedback_route.next_step_id == 'recollect_sources'"
    )
    assert edges["feedback-retry-to-writer"].condition == EdgeCondition.CONDITIONAL
    assert edges["feedback-retry-to-writer"].condition_expr == (
        "outcome.outputs.agent_feedback_route.next_step_id == 'writer_agent'"
    )
    assert edges["feedback-pass-to-editor"].condition == EdgeCondition.CONDITIONAL
    assert edges["feedback-pass-to-editor"].condition_expr == (
        "outcome.outputs.agent_feedback_route.next_step_id == 'editor_agent'"
    )
    assert edges["feedback-to-finalize"].condition == EdgeCondition.CONDITIONAL
    assert edges["feedback-to-finalize"].condition_expr == (
        "outcome.outputs.agent_feedback_route.next_step_id == 'finalize_report'"
    )
    assert (
        edges["feedback-recollect-to-sources"].priority
        < edges["feedback-retry-to-writer"].priority
    )
    assert (
        edges["feedback-retry-to-writer"].priority
        < edges["feedback-to-finalize"].priority
    )


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
        "daily.recollect_sources",
        "daily.finalize_report",
    ]:
        function_registry.register(implementation, lambda buffer: {})

    return build_default_step_runner_registry(
        function_registry,
        tool_registry=build_daily_agent_tool_registry(),
        agent_runner=build_profiled_daily_agent_runner(profile=PROFILE_AGENTIC_OFFLINE),
        agent_registry=build_daily_agent_registry(),
    )


def _step_signatures(
    steps,
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
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
