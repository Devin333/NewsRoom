from __future__ import annotations

from framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    LEGACY_DAILY_WORKFLOW_ID,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE as PROFILE_LIVE_OFFLINE,
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

WORKFLOW_ID = LEGACY_DAILY_WORKFLOW_ID
WORKFLOW_VERSION = "0.1.0"


def build_daily_intelligence_workflow(profile: str) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Daily Intelligence Live",
        version=WORKFLOW_VERSION,
        description="Daily intelligence workflow for live and live-offline profiles.",
        start_step_id="collect_sources",
        terminal_step_ids=["quality_gate"],
        steps=[
            *build_source_and_evidence_steps(),
            StepSpec(
                step_id="draft_report",
                implementation="daily.draft_report",
                read_keys=with_namespaced_read_keys([
                    "request",
                    "evidence_bundle",
                    "source_errors",
                    "source_pipeline_metrics",
                ]),
                write_keys=with_namespaced_write_keys(["report_draft", "memory_context", "historian_context"]),
                required_output_keys=["report_draft"],
            ),
            StepSpec(
                step_id="quality_gate",
                implementation="daily.quality_gate",
                read_keys=with_namespaced_read_keys([
                    "report_draft",
                    "evidence_bundle",
                    "verified_findings",
                    "quality_events",
                ]),
                write_keys=with_namespaced_write_keys([
                    "citation_check_result",
                    "editor_review",
                    "support_matrix",
                    "report_quality_summary",
                    "quality_events",
                    "quality_gate_metrics",
                    "quality_result",
                    "quality_route",
                    "rewrite_policy",
                    "rewrite_instructions",
                    "memory_quality_result",
                    "rewritten_report_draft",
                    "human_review_request",
                    "final_report",
                    "report_markdown",
                    "blocked_report",
                ]),
                required_output_keys=[
                    "citation_check_result",
                    "editor_review",
                    "support_matrix",
                    "report_quality_summary",
                    "quality_events",
                    "quality_gate_metrics",
                    "quality_result",
                ],
                metadata={
                    "optional_read_keys": with_namespaced_read_keys([
                        "memory_context",
                        "historian_context",
                        "memory_query_repository",
                    ])
                },
            ),
        ],
        edges=[
            EdgeSpec("collect-to-require", "collect_sources", "require_sources"),
            EdgeSpec("require-to-normalize", "require_sources", "normalize_sources"),
            EdgeSpec("normalize-to-dedupe", "normalize_sources", "deduplicate_sources"),
            EdgeSpec("dedupe-to-rank", "deduplicate_sources", "rank_sources"),
            EdgeSpec("rank-to-evidence", "rank_sources", "build_evidence"),
            EdgeSpec("evidence-to-draft", "build_evidence", "draft_report"),
            EdgeSpec("draft-to-quality", "draft_report", "quality_gate"),
        ],
        policies=daily_workflow_runtime_policy(),
        metadata={"profile": profile, "product_path": profile == PROFILE_LIVE},
    )


