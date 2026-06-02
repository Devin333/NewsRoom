from __future__ import annotations

from typing import Any

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._service import BoardServiceBase
from business.boards.productized.artifacts import ProductizedArtifactMetadataService
from business.boards.productized.context import analysis_context_from_request, run_id_from_request
from business.boards.productized.deduplication import ProductizedDeduplicationService
from business.boards.productized.entity_extraction import ProductizedEntityExtractionService
from business.boards.productized.evidence import ProductizedEvidenceService
from business.boards.productized.feedback import ProductizedFeedbackLearningService
from business.boards.productized.improvement import ProductizedImprovementWorkflowService
from business.boards.productized.models import ProductizedRunState
from business.boards.productized.output import ProductizedBoardOutputService
from business.boards.productized.preparation import ProductizedSignalPreparationService
from business.boards.productized.quality import ProductizedQualitySummaryService
from business.boards.productized.ranking import ProductizedRankingService
from business.boards.productized.subscription import ProductizedSubscriptionService
from business.boards.productized.trends import ProductizedTrendAnalysisService
from business.foundation import AnalysisContext, BoardType
from business.foundation.skills import BusinessSkillRuntime


class ProductizedBoardUseCases:
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
        self.board_service = board_service
        self.signal_preparation_service = ProductizedSignalPreparationService(
            board_type=board_type,
            skill_runtime=skill_runtime,
            improvement_service=improvement_service,
        )
        self.entity_extraction_service = ProductizedEntityExtractionService(
            skill_runtime=skill_runtime,
        )
        self.deduplication_service = ProductizedDeduplicationService(
            skill_runtime=skill_runtime,
        )
        self.evidence_service = ProductizedEvidenceService()
        self.ranking_service = ProductizedRankingService()
        self.trend_analysis_service = ProductizedTrendAnalysisService(
            skill_runtime=skill_runtime,
        )
        self.quality_summary_service = ProductizedQualitySummaryService(
            skill_runtime=skill_runtime,
        )
        self.feedback_learning_service = ProductizedFeedbackLearningService(
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
        self.improvement_workflow_service = ProductizedImprovementWorkflowService(
            improvement_service=improvement_service,
        )
        self.artifact_metadata_service = ProductizedArtifactMetadataService()
        self.output_service = ProductizedBoardOutputService(
            board_service=board_service,
            skill_runtime=skill_runtime,
        )
        self.subscription_service = ProductizedSubscriptionService(
            board_type=board_type,
        )

    def prepare_signals(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.signal_preparation_service.prepare(request)

    def classify_board_signals(self, *, context: AnalysisContext, prepared_signals: list[Any]) -> dict[str, Any]:
        return {"board_signals": self.board_service.select_signals(prepared_signals, context=context)}

    def extract_entities(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.entity_extraction_service.extract(
            request=request,
            board_signals=board_signals,
            productized_run=productized_run,
        )

    def build_evidence(
        self,
        *,
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.evidence_service.build_outputs(
            board_signals=board_signals,
            productized_run=productized_run,
        )

    def deduplicate_events(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.deduplication_service.deduplicate(
            request=request,
            board_signals=board_signals,
            productized_run=productized_run,
        )

    def rank_items(self, *, deduplicated_signals: list[Any]) -> dict[str, Any]:
        return {"ranked_signals": self.ranking_service.rank(deduplicated_signals)}

    def analyze_trends(
        self,
        *,
        request: dict[str, Any],
        ranked_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.trend_analysis_service.analyze(
            request=request,
            ranked_signals=ranked_signals,
            productized_run=productized_run,
        )

    def build_board_output(
        self,
        *,
        request: dict[str, Any],
        context: AnalysisContext,
        ranked_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.output_service.build(
            request=request,
            context=context,
            ranked_signals=ranked_signals,
            productized_run=productized_run,
        ).to_step_outputs()

    def build_quality_summary(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        return self.quality_summary_service.build_summary(
            request=request,
            board_run_result=board_run_result,
            productized_run=productized_run,
        )

    def build_subscription_payload(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        board_output: dict[str, Any],
        quality_summary: dict[str, Any],
    ) -> dict[str, Any]:
        return self.subscription_service.build(
            request=request,
            board_run_result=board_run_result,
            board_output=board_output,
            quality_summary=quality_summary,
        )

    def build_feedback_events(self, *, board_run_result: Any) -> dict[str, Any]:
        return self.feedback_learning_service.collect(board_run_result=board_run_result)

    def build_improvement_recommendations(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        quality_summary: dict[str, Any],
        cards: list[dict[str, Any]],
        feedback_events: list[dict[str, Any]],
        learning_signals: list[dict[str, Any]],
        subscription_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.improvement_workflow_service.build(
            run_id=run_id_from_request(request, self.board_type),
            board_type=self.board_type.value,
            request=request,
            board_run_result=board_run_result,
            quality_summary=quality_summary,
            cards=cards,
            feedback_events=feedback_events,
            learning_signals=learning_signals,
            subscription_payload=subscription_payload,
        )

    def publish_board_artifacts(
        self,
        *,
        request: dict[str, Any],
        cards: list[dict[str, Any]],
        quality_summary: dict[str, Any],
        subscription_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.artifact_metadata_service.build_outputs(
            board_type=self.board_type,
            request=request,
            cards=cards,
            quality_summary=quality_summary,
            subscription_payload=subscription_payload,
        )

__all__ = ["ProductizedBoardUseCases", "analysis_context_from_request", "run_id_from_request"]
