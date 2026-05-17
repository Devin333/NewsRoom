from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, StepType, WorkflowSpec
from workflows.daily_intelligence.agent_registry import PROFILE_AGENTIC_LIVE
from workflows.daily_intelligence.agents import (
    ANALYST_AGENT_ID,
    EDITOR_AGENT_ID,
    PLANNER_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
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
            *_source_and_evidence_steps(),
            _planner_agent_step(),
            _analyst_agent_step(),
            _writer_agent_step(),
            _verifier_agent_step(),
            _editor_agent_step(),
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
            EdgeSpec("verifier-to-editor", "verifier_agent", "editor_agent"),
            EdgeSpec("editor-to-finalize", "editor_agent", "finalize_report"),
        ],
        metadata={"profile": profile, "product_path": profile == PROFILE_AGENTIC_LIVE},
    )


def _source_and_evidence_steps() -> list[StepSpec]:
    return [
        StepSpec(
            step_id="collect_sources",
            implementation="daily.collect_sources",
            read_keys=["request"],
            write_keys=[
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
            ],
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
            ],
        ),
        StepSpec(
            step_id="require_sources",
            implementation="daily.require_sources",
            read_keys=["raw_items", "source_errors"],
            write_keys=["source_collection_status"],
            required_output_keys=["source_collection_status"],
        ),
        StepSpec(
            step_id="normalize_sources",
            implementation="daily.normalize_sources",
            read_keys=[
                "raw_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
            ],
            write_keys=[
                "normalized_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
            ],
            required_output_keys=[
                "normalized_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
            ],
        ),
        StepSpec(
            step_id="deduplicate_sources",
            implementation="daily.deduplicate_sources",
            read_keys=[
                "normalized_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
            ],
            write_keys=[
                "deduplicated_items",
                "source_errors",
                "source_duplicate_groups",
                "source_events",
                "source_pipeline_metrics",
            ],
            required_output_keys=[
                "deduplicated_items",
                "source_errors",
                "source_duplicate_groups",
                "source_events",
                "source_pipeline_metrics",
            ],
        ),
        StepSpec(
            step_id="rank_sources",
            implementation="daily.rank_sources",
            read_keys=[
                "deduplicated_items",
                "request",
                "source_errors",
                "skipped_sources",
                "failed_sources",
                "source_selection_report",
                "source_events",
                "source_pipeline_metrics",
            ],
            write_keys=[
                "ranked_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
                "source_coverage_report",
                "source_quality_scores",
                "source_quality_summary_report",
                "source_ranking_scores",
                "source_freshness_report",
                "source_traceability_report",
                "source_governance_report",
            ],
            required_output_keys=[
                "ranked_items",
                "source_errors",
                "source_events",
                "source_pipeline_metrics",
                "source_coverage_report",
                "source_quality_scores",
                "source_quality_summary_report",
                "source_ranking_scores",
                "source_freshness_report",
                "source_traceability_report",
                "source_governance_report",
            ],
        ),
        StepSpec(
            step_id="build_evidence",
            implementation="daily.build_evidence",
            read_keys=["ranked_items"],
            write_keys=[
                "evidence_bundle",
                "evidence_scores",
                "candidate_claims",
                "verified_findings",
                "quality_events",
            ],
            required_output_keys=[
                "evidence_bundle",
                "evidence_scores",
                "candidate_claims",
                "verified_findings",
                "quality_events",
            ],
        ),
    ]


def _planner_agent_step() -> StepSpec:
    return StepSpec(
        step_id="planner_agent",
        name="Planner Agent",
        implementation=PLANNER_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=["request"],
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
        metadata=_agent_step_metadata(
            PLANNER_AGENT_ID,
            prefix="planner",
        ),
    )


def _analyst_agent_step() -> StepSpec:
    return StepSpec(
        step_id="analyst_agent",
        name="Analyst Agent",
        implementation=ANALYST_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=[
            "request",
            "research_plan",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ],
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
        read_keys=[
            "request",
            "research_plan",
            "analysis_result",
            "verified_findings",
            "evidence_bundle",
            "source_errors",
            "source_pipeline_metrics",
        ],
        write_keys=[
            "report_draft",
            "writer_notes",
            "writer_agent_loop_result",
            "writer_agent_loop_events",
            "writer_agent_loop_metrics",
            "writer_agent_loop_diagnostics",
            "writer_agent_loop_trace",
            "writer_llm_call_artifacts",
        ],
        required_output_keys=["report_draft"],
        metadata=_agent_step_metadata(
            WRITER_AGENT_ID,
            prefix="writer",
        ),
    )


def _verifier_agent_step() -> StepSpec:
    return StepSpec(
        step_id="verifier_agent",
        name="Verifier Agent",
        implementation=VERIFIER_AGENT_ID,
        step_type=StepType.AGENT_LOOP,
        read_keys=[
            "report_draft",
            "evidence_bundle",
            "candidate_claims",
            "verified_findings",
        ],
        write_keys=[
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
        ],
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
        read_keys=[
            "report_draft",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
        ],
        write_keys=[
            "editor_review",
            "edited_report_draft",
            "editor_notes",
            "editor_agent_loop_result",
            "editor_agent_loop_events",
            "editor_agent_loop_metrics",
            "editor_agent_loop_diagnostics",
            "editor_agent_loop_trace",
            "editor_llm_call_artifacts",
        ],
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
        read_keys=[
            "request",
            "report_draft",
            "edited_report_draft",
            "editor_review",
            "verification_result",
            "citation_check_result",
            "support_matrix",
            "evidence_bundle",
            "verified_findings",
            "quality_events",
        ],
        write_keys=[
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
        ],
        required_output_keys=["quality_result", "quality_gate_metrics"],
        metadata={"optional_read_keys": ["edited_report_draft"]},
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
