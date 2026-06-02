from __future__ import annotations

from framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_LIVE
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
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_read_keys,
    with_namespaced_write_keys,
)
from business.boards.cross_board.workflows.daily_intelligence.workflow_runtime_policy import (
    daily_workflow_runtime_policy,
)


AGENTIC_WORKFLOW_ID = "daily-intelligence-agentic"
AGENTIC_WORKFLOW_VERSION = "0.1.0"


def build_agentic_daily_intelligence_workflow(profile: str) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=AGENTIC_WORKFLOW_ID,
        name="Daily Intelligence Agentic",
        version=AGENTIC_WORKFLOW_VERSION,
        description="Daily intelligence workflow with planner, analyst, writer, verifier, and editor AgentLoop steps.",
        start_step_id="collect_sources",
        terminal_step_ids=["finalize_report"],
        steps=[
            *build_source_and_evidence_steps(),
            _planner_agent_step(),
            _analyst_agent_step(),
            _writer_agent_step(),
            _verifier_agent_step(),
            _editor_agent_step(),
            _collect_agent_feedback_step(),
            _recollect_sources_step(),
            _finalize_report_step(),
        ],
        edges=[
            EdgeSpec("collect-to-require", "collect_sources", "require_sources"),
            EdgeSpec("require-to-normalize", "require_sources", "normalize_sources"),
            EdgeSpec("normalize-to-dedupe", "normalize_sources", "deduplicate_sources"),
            EdgeSpec("dedupe-to-rank", "deduplicate_sources", "rank_sources"),
            EdgeSpec("rank-to-evidence", "rank_sources", "build_evidence"),
            EdgeSpec("evidence-to-planner", "build_evidence", "planner_agent"),
            EdgeSpec("planner-to-analyst", "planner_agent", "analyst_agent"),
            EdgeSpec("analyst-to-writer", "analyst_agent", "writer_agent"),
            EdgeSpec("writer-to-verifier", "writer_agent", "verifier_agent"),
            EdgeSpec("verifier-to-feedback", "verifier_agent", "collect_agent_feedback"),
            EdgeSpec("editor-to-feedback", "editor_agent", "collect_agent_feedback"),
            EdgeSpec(
                "feedback-recollect-to-sources",
                "collect_agent_feedback",
                "recollect_sources",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="outcome.outputs.agent_feedback_route.next_step_id == 'recollect_sources'",
                priority=-20,
            ),
            EdgeSpec("recollect-to-normalize", "recollect_sources", "normalize_sources"),
            EdgeSpec(
                "feedback-retry-to-writer",
                "collect_agent_feedback",
                "writer_agent",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="outcome.outputs.agent_feedback_route.next_step_id == 'writer_agent'",
                priority=-10,
            ),
            EdgeSpec(
                "feedback-pass-to-editor",
                "collect_agent_feedback",
                "editor_agent",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="outcome.outputs.agent_feedback_route.next_step_id == 'editor_agent'",
            ),
            EdgeSpec(
                "feedback-to-finalize",
                "collect_agent_feedback",
                "finalize_report",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="outcome.outputs.agent_feedback_route.next_step_id == 'finalize_report'",
                priority=10,
            ),
        ],
        policies=daily_workflow_runtime_policy(),
        metadata={"profile": profile, "product_path": profile == PROFILE_AGENTIC_LIVE},
    )


def _planner_agent_step() -> StepSpec:
    return StepSpec(
        step_id="planner_agent",
        name="Planner Agent",
        implementation=PLANNER_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=with_namespaced_read_keys([
            "request",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ]),
        write_keys=[
            "research_plan",
            "planner_notes",
            "planner_agent_loop_result",
            "planner_agent_loop_events",
            "planner_agent_loop_metrics",
            "planner_agent_loop_diagnostics",
            "planner_agent_loop_trace",
            "planner_llm_call_artifacts",
        ],
        required_output_keys=["research_plan"],
        metadata={
            **_agent_step_metadata(
                PLANNER_AGENT_ID,
                prefix="planner",
            ),
            "optional_read_keys": with_namespaced_read_keys([
                "agent_feedback_events",
                "agent_feedback_summary",
                "agent_feedback_route",
                "agent_feedback_loop_state",
                "source_recollection_profile",
                "source_recollection_execution_plan",
                "source_recollection_execution_report",
                "source_recollection_quality_assessment",
            ]),
        },
    )


def _analyst_agent_step() -> StepSpec:
    return StepSpec(
        step_id="analyst_agent",
        name="Analyst Agent",
        implementation=ANALYST_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=with_namespaced_read_keys([
            "request",
            "research_plan",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ]),
        write_keys=[
            "analysis_result",
            "analyst_notes",
            "analyst_agent_loop_result",
            "analyst_agent_loop_events",
            "analyst_agent_loop_metrics",
            "analyst_agent_loop_diagnostics",
            "analyst_agent_loop_trace",
            "analyst_llm_call_artifacts",
        ],
        required_output_keys=["analysis_result"],
        metadata=_agent_step_metadata(
            ANALYST_AGENT_ID,
            prefix="analyst",
        ),
    )


def _writer_agent_step() -> StepSpec:
    return StepSpec(
        step_id="writer_agent",
        name="Writer Agent",
        implementation=WRITER_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=with_namespaced_read_keys([
            "request",
            "research_plan",
            "analysis_result",
            "verified_findings",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ]),
        write_keys=with_namespaced_write_keys([
            "report_draft",
            "writer_notes",
            "writer_agent_loop_result",
            "writer_agent_loop_events",
            "writer_agent_loop_metrics",
            "writer_agent_loop_diagnostics",
            "writer_agent_loop_trace",
            "writer_llm_call_artifacts",
        ]),
        required_output_keys=["report_draft"],
        metadata={
            **_agent_step_metadata(
                WRITER_AGENT_ID,
                prefix="writer",
            ),
            "optional_read_keys": with_namespaced_read_keys([
                "citation_check_result",
                "support_matrix",
                "verification_result",
                "agent_feedback_events",
                "agent_feedback_summary",
                "agent_feedback_route",
                "agent_feedback_loop_state",
            ]),
        },
    )


def _verifier_agent_step() -> StepSpec:
    return StepSpec(
        step_id="verifier_agent",
        name="Verifier Agent",
        implementation=VERIFIER_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=with_namespaced_read_keys([
            "report_draft",
            "evidence_bundle",
            "candidate_claims",
            "verified_findings",
        ]),
        write_keys=with_namespaced_write_keys([
            "citation_check_result",
            "support_matrix",
            "verification_result",
            "verifier_notes",
            "verifier_agent_loop_result",
            "verifier_agent_loop_events",
            "verifier_agent_loop_metrics",
            "verifier_agent_loop_diagnostics",
            "verifier_agent_loop_trace",
            "verifier_llm_call_artifacts",
        ]),
        required_output_keys=["verification_result"],
        metadata=_agent_step_metadata(
            VERIFIER_AGENT_ID,
            prefix="verifier",
        ),
    )


def _editor_agent_step() -> StepSpec:
    return StepSpec(
        step_id="editor_agent",
        name="Editor Agent",
        implementation=EDITOR_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=with_namespaced_read_keys([
            "report_draft",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
        ]),
        write_keys=with_namespaced_write_keys([
            "editor_review",
            "edited_report_draft",
            "editor_notes",
            "editor_agent_loop_result",
            "editor_agent_loop_events",
            "editor_agent_loop_metrics",
            "editor_agent_loop_diagnostics",
            "editor_agent_loop_trace",
            "editor_llm_call_artifacts",
        ]),
        required_output_keys=["editor_review"],
        metadata=_agent_step_metadata(
            EDITOR_AGENT_ID,
            prefix="editor",
        ),
    )


def _finalize_report_step() -> StepSpec:
    return StepSpec(
        step_id="finalize_report",
        implementation="daily.finalize_report",
        step_type=StepType.FUNCTION,
        read_keys=with_namespaced_read_keys([
            "request",
            "report_draft",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
            "verified_findings",
            "quality_events",
            "agent_feedback_events",
            "agent_feedback_summary",
            "agent_feedback_route",
        ]),
        write_keys=with_namespaced_write_keys([
            "report_quality_summary",
            "quality_events",
            "quality_gate_metrics",
            "quality_result",
            "quality_route",
            "rewrite_instructions",
            "human_review_request",
            "final_report",
            "report_markdown",
            "blocked_report",
        ]),
        required_output_keys=["quality_result", "quality_gate_metrics"],
        metadata={
            "optional_read_keys": with_namespaced_read_keys([
                "edited_report_draft",
                "editor_review",
            ])
        },
    )


def _collect_agent_feedback_step() -> StepSpec:
    return StepSpec(
        step_id="collect_agent_feedback",
        implementation="daily.collect_agent_feedback",
        step_type=StepType.FUNCTION,
        read_keys=with_namespaced_read_keys([
            "analysis_result",
            "verification_result",
            "citation_check_result",
            "support_matrix",
        ]),
        write_keys=with_namespaced_write_keys([
            "agent_feedback_events",
            "agent_feedback_summary",
            "agent_feedback_route",
            "agent_feedback_loop_state",
            "source_recollection_profile",
            "source_recollection_execution_plan",
        ]),
        required_output_keys=["agent_feedback_summary"],
        metadata={
            "optional_read_keys": with_namespaced_read_keys([
                "editor_review",
                "agent_feedback_loop_state",
            ])
        },
    )


def _recollect_sources_step() -> StepSpec:
    return StepSpec(
        step_id="recollect_sources",
        implementation="daily.recollect_sources",
        step_type=StepType.FUNCTION,
        read_keys=with_namespaced_read_keys([
            "request",
            "source_recollection_execution_plan",
        ]),
        write_keys=with_namespaced_write_keys([
            "raw_items",
            "source_errors",
            "skipped_sources",
            "failed_sources",
            "source_fetch_requests",
            "source_fetch_results",
            "source_health_updates",
            "source_health_report",
            "source_events",
            "source_pipeline_metrics",
            "source_connector_dispatch_report",
            "source_error_policy_report",
            "source_fallback_report",
            "source_selection_report",
            "source_coverage_report",
            "source_recollection_execution_report",
            "source_recollection_quality_assessment",
        ]),
        required_output_keys=[
            "raw_items",
            "source_errors",
            "skipped_sources",
            "failed_sources",
            "source_fetch_requests",
            "source_fetch_results",
            "source_health_updates",
            "source_health_report",
            "source_events",
            "source_pipeline_metrics",
            "source_connector_dispatch_report",
            "source_error_policy_report",
            "source_fallback_report",
            "source_selection_report",
            "source_coverage_report",
            "source_recollection_execution_report",
            "source_recollection_quality_assessment",
        ],
        metadata={
            "optional_read_keys": with_namespaced_read_keys([
                "raw_items",
                "source_errors",
                "skipped_sources",
                "failed_sources",
                "source_fetch_requests",
                "source_fetch_results",
                "source_health_updates",
                "source_events",
                "source_pipeline_metrics",
            ])
        },
    )


def _agent_step_metadata(agent_id: str, *, prefix: str) -> dict[str, str]:
    return {
        "agent_id": agent_id,
        "result_key": f"{prefix}_agent_loop_result",
        "events_key": f"{prefix}_agent_loop_events",
        "metrics_key": f"{prefix}_agent_loop_metrics",
        "diagnostics_key": f"{prefix}_agent_loop_diagnostics",
        "trace_key": f"{prefix}_agent_loop_trace",
        "llm_artifacts_key": f"{prefix}_llm_call_artifacts",
    }
