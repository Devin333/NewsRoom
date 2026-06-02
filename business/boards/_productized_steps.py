from __future__ import annotations

from typing import Any

from framework.specs import EdgeSpec, StepSpec, WorkflowSpec

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._service import BoardServiceBase
from business.boards.productized import ProductizedBoardUseCases
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillRuntime


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


class ProductizedBoardSteps:
    def __init__(
        self,
        *,
        board_type: BoardType,
        board_service: BoardServiceBase,
        skill_runtime: BusinessSkillRuntime,
        feedback_service: BoardFeedbackService,
        improvement_service: BoardImprovementService,
    ) -> None:
        self.board_type = board_type
        self.usecases = ProductizedBoardUseCases(
            board_type=board_type,
            board_service=board_service,
            skill_runtime=skill_runtime,
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )

    def register(self, registry: Any) -> None:
        prefix = self.board_type.value
        registry.register(f"{prefix}.prepare_signals", self.prepare_signals)
        registry.register(f"{prefix}.classify_board_signals", self.classify_board_signals)
        registry.register(f"{prefix}.extract_entities", self.extract_entities)
        registry.register(f"{prefix}.build_evidence", self.build_evidence)
        registry.register(f"{prefix}.deduplicate_events", self.deduplicate_events)
        registry.register(f"{prefix}.rank_items", self.rank_items)
        registry.register(f"{prefix}.analyze_trends", self.analyze_trends)
        registry.register(f"{prefix}.build_board_output", self.build_board_output)
        registry.register(f"{prefix}.build_quality_summary", self.build_quality_summary)
        registry.register(f"{prefix}.build_subscription_payload", self.build_subscription_payload)
        registry.register(f"{prefix}.build_feedback_events", self.build_feedback_events)
        registry.register(f"{prefix}.build_improvement_recommendations", self.build_improvement_recommendations)
        registry.register(f"{prefix}.publish_board_artifacts", self.publish_board_artifacts)

    def prepare_signals(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.prepare_signals(buffer.read("request"))

    def classify_board_signals(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.classify_board_signals(
            context=buffer.read("context"),
            prepared_signals=buffer.read("prepared_signals"),
        )

    def extract_entities(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.extract_entities(
            request=buffer.read("request"),
            board_signals=buffer.read("board_signals"),
            productized_run=buffer.read("productized_run"),
        )

    def build_evidence(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_evidence(
            board_signals=buffer.read("board_signals"),
            productized_run=buffer.read("productized_run"),
        )

    def deduplicate_events(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.deduplicate_events(
            request=buffer.read("request"),
            board_signals=buffer.read("board_signals"),
            productized_run=buffer.read("productized_run"),
        )

    def rank_items(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.rank_items(deduplicated_signals=buffer.read("deduplicated_signals"))

    def analyze_trends(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.analyze_trends(
            request=buffer.read("request"),
            ranked_signals=buffer.read("ranked_signals"),
            productized_run=buffer.read("productized_run"),
        )

    def build_board_output(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_board_output(
            request=buffer.read("request"),
            context=buffer.read("context"),
            ranked_signals=buffer.read("ranked_signals"),
            productized_run=buffer.read("productized_run"),
        )

    def build_quality_summary(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_quality_summary(
            request=buffer.read("request"),
            board_run_result=buffer.read("board_run_result"),
            productized_run=buffer.read("productized_run"),
        )

    def build_subscription_payload(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_subscription_payload(
            request=buffer.read("request"),
            board_run_result=buffer.read("board_run_result"),
            board_output=buffer.read("board_output"),
            quality_summary=buffer.read("quality_summary"),
        )

    def build_feedback_events(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_feedback_events(board_run_result=buffer.read("board_run_result"))

    def build_improvement_recommendations(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.build_improvement_recommendations(
            request=buffer.read("request"),
            board_run_result=buffer.read("board_run_result"),
            quality_summary=buffer.read("quality_summary"),
            cards=buffer.read("cards"),
            feedback_events=buffer.read("feedback_events"),
            learning_signals=buffer.read("learning_signals"),
            subscription_payload=buffer.read("subscription_payload"),
        )

    def publish_board_artifacts(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.publish_board_artifacts(
            request=buffer.read("request"),
            cards=buffer.read("cards"),
            quality_summary=buffer.read("quality_summary"),
            subscription_payload=buffer.read("subscription_payload"),
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
                read_keys=_read_keys(step_id),
                write_keys=_write_keys(step_id),
                required_output_keys=_write_keys(step_id),
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


def _read_keys(step_id: str) -> list[str]:
    mapping = {
        "prepare_signals": ["request"],
        "classify_board_signals": ["context", "prepared_signals"],
        "extract_entities": ["request", "board_signals", "productized_run"],
        "build_evidence": ["board_signals", "productized_run"],
        "deduplicate_events": ["request", "board_signals", "productized_run"],
        "rank_items": ["deduplicated_signals"],
        "analyze_trends": ["request", "ranked_signals", "productized_run"],
        "build_board_output": ["request", "context", "ranked_signals", "productized_run"],
        "build_quality_summary": ["request", "board_run_result", "productized_run"],
        "build_subscription_payload": ["request", "board_run_result", "board_output", "quality_summary"],
        "build_feedback_events": ["board_run_result"],
        "build_improvement_recommendations": ["request", "board_run_result", "quality_summary", "cards", "feedback_events", "learning_signals", "subscription_payload"],
        "publish_board_artifacts": ["request", "cards", "quality_summary", "subscription_payload"],
    }
    return mapping[step_id]


def _write_keys(step_id: str) -> list[str]:
    mapping = {
        "prepare_signals": ["context", "raw_signals", "prepared_signals", "source_reliability_results", "skill_traces", "improvement_context", "productized_run"],
        "classify_board_signals": ["board_signals"],
        "extract_entities": ["extracted_entities", "skill_traces", "productized_run"],
        "build_evidence": ["evidence_refs", "evidence_items", "productized_run"],
        "deduplicate_events": ["deduplicated_signals", "deduplication_result", "skill_traces", "productized_run"],
        "rank_items": ["ranked_signals"],
        "analyze_trends": ["trend_analysis", "skill_traces", "productized_run"],
        "build_board_output": ["board_run_result", "board_output", "cards", "detail_pages", "insights", "summary_md", "skill_traces", "productized_run"],
        "build_quality_summary": ["quality_summary", "evidence_checking", "skill_traces", "productized_run"],
        "build_subscription_payload": ["subscription_payload"],
        "build_feedback_events": ["feedback_events", "learning_signals"],
        "build_improvement_recommendations": ["improvement_recommendations", "improvement_proposals", "applied_policy_experiments", "skipped_policy_experiments", "applied_overrides", "improvement_measurement", "self_improvement_report"],
        "publish_board_artifacts": ["artifact_metadata"],
    }
    return mapping[step_id]


__all__ = ["PRODUCTIZED_BOARD_STEPS", "ProductizedBoardSteps", "build_productized_board_workflow"]
