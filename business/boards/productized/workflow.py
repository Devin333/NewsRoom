from __future__ import annotations

from framework.specs import EdgeSpec, StepSpec, WorkflowSpec

from business.foundation import BoardType


PRODUCTIZED_BOARD_STEPS = (
    "prepare_signals",
    "classify_board_signals",
    "extract_entities",
    "build_evidence",
    "deduplicate_events",
    "rank_items",
    "analyze_trends",
    "build_board_output",
    "build_quality_summary",
    "build_subscription_payload",
    "build_feedback_events",
    "build_improvement_recommendations",
    "publish_board_artifacts",
)


def build_productized_board_workflow(board_type: BoardType) -> WorkflowSpec:
    workflow_id = f"{board_type.value}-productized-board"
    steps = []
    for step_id in PRODUCTIZED_BOARD_STEPS:
        steps.append(
            StepSpec(
                step_id=step_id,
                name=step_id.replace("_", " ").title(),
                implementation=f"{board_type.value}.{step_id}",
                read_keys=read_keys_for_productized_step(step_id),
                write_keys=write_keys_for_productized_step(step_id),
                required_output_keys=write_keys_for_productized_step(step_id),
            )
        )
    return WorkflowSpec(
        workflow_id=workflow_id,
        name=f"{board_type.value} Productized Board",
        version="1.0.0",
        description=f"Productized business workflow for {board_type.value}.",
        start_step_id=PRODUCTIZED_BOARD_STEPS[0],
        terminal_step_ids=[PRODUCTIZED_BOARD_STEPS[-1]],
        steps=steps,
        edges=[
            EdgeSpec(
                edge_id=f"{left}_to_{right}",
                source_step_id=left,
                target_step_id=right,
            )
            for left, right in zip(PRODUCTIZED_BOARD_STEPS, PRODUCTIZED_BOARD_STEPS[1:])
        ],
        input_schema={
            "type": "object",
            "required": ["signals"],
            "properties": {
                "signals": {"type": "array"},
                "topic": {"type": ["string", "null"]},
                "run_id": {"type": ["string", "null"]},
            },
        },
        output_schema={"type": "object"},
        metadata={"board_type": board_type.value, "productized": True},
    )


def read_keys_for_productized_step(step_id: str) -> list[str]:
    return _READ_KEYS[step_id]


def write_keys_for_productized_step(step_id: str) -> list[str]:
    return _WRITE_KEYS[step_id]


_READ_KEYS = {
    "prepare_signals": ["request"],
    "classify_board_signals": ["context", "prepared_signals"],
    "extract_entities": ["request", "board_signals", "productized_run"],
    "build_evidence": ["board_signals", "productized_run"],
    "deduplicate_events": ["request", "board_signals", "productized_run"],
    "rank_items": ["deduplicated_signals"],
    "analyze_trends": ["request", "ranked_signals", "productized_run"],
    "build_board_output": ["request", "context", "ranked_signals", "productized_run"],
    "build_quality_summary": ["request", "board_run_result", "productized_run"],
    "build_subscription_payload": ["request", "board_run_result", "board_output", "quality_summary", "report_summary"],
    "build_feedback_events": ["board_run_result"],
    "build_improvement_recommendations": [
        "request",
        "board_run_result",
        "quality_summary",
        "cards",
        "feedback_events",
        "learning_signals",
        "subscription_payload",
        "productized_run",
    ],
    "publish_board_artifacts": ["request", "cards", "quality_summary", "subscription_payload"],
}


_WRITE_KEYS = {
    "prepare_signals": ["context", "raw_signals", "prepared_signals", "source_reliability_results", "skill_traces", "improvement_context", "productized_run"],
    "classify_board_signals": ["board_signals"],
    "extract_entities": ["extracted_entities", "skill_traces", "productized_run"],
    "build_evidence": ["evidence_refs", "evidence_items", "productized_run"],
    "deduplicate_events": ["deduplicated_signals", "deduplication_result", "skill_traces", "productized_run"],
    "rank_items": ["ranked_signals"],
    "analyze_trends": ["trend_analysis", "skill_traces", "productized_run"],
    "build_board_output": [
        "board_run_result",
        "board_output",
        "cards",
        "detail_pages",
        "insights",
        "report_summary",
        "summary_md",
        "skill_traces",
        "productized_run",
    ],
    "build_quality_summary": ["quality_summary", "evidence_checking", "skill_traces", "productized_run"],
    "build_subscription_payload": ["subscription_payload"],
    "build_feedback_events": ["feedback_events", "learning_signals"],
    "build_improvement_recommendations": [
        "improvement_recommendations",
        "improvement_proposals",
        "policy_experiment_profiles",
        "policy_experiment_profile_ids",
        "applied_policy_experiments",
        "skipped_policy_experiments",
        "applied_overrides",
        "improvement_measurement",
        "self_improvement_report",
    ],
    "publish_board_artifacts": ["artifact_metadata"],
}


__all__ = [
    "PRODUCTIZED_BOARD_STEPS",
    "build_productized_board_workflow",
    "read_keys_for_productized_step",
    "write_keys_for_productized_step",
]
