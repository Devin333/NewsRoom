from __future__ import annotations

from typing import Any

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._service import BoardServiceBase
from business.boards.productized.usecases import ProductizedBoardUseCases
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillRuntime


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
            productized_run=buffer.read("productized_run"),
        )

    def publish_board_artifacts(self, buffer: Any) -> dict[str, Any]:
        return self.usecases.publish_board_artifacts(
            request=buffer.read("request"),
            cards=buffer.read("cards"),
            quality_summary=buffer.read("quality_summary"),
            subscription_payload=buffer.read("subscription_payload"),
        )


__all__ = ["ProductizedBoardSteps"]
