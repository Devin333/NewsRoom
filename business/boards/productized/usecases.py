from __future__ import annotations

from typing import Any

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._service import BoardServiceBase
from business.boards.productized.artifacts import ProductizedArtifactMetadataService
from business.boards.productized.evidence import ProductizedEvidenceService
from business.boards.productized.feedback import ProductizedFeedbackLearningService
from business.boards.productized.improvement import ProductizedImprovementWorkflowService
from business.boards.productized.models import ProductizedRunState
from business.boards.productized.payloads import (
    card_report_item,
    signal_item_payload,
    source_reliability_content_payload,
    source_reliability_source_payload,
    summary_markdown,
)
from business.boards.productized.quality import ProductizedQualityService
from business.boards.productized.ranking import ProductizedRankingService
from business.boards.productized.trends import ProductizedTrendEventService
from business.foundation import AnalysisContext, BoardType, RunContext
from business.foundation.skills import BusinessSkillRuntime
from business.foundation.subscription import DeliveryPlanBuilder, SubscriptionPayloadBuilder
from business.layers.signal import SignalPipeline


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
        self.skill_runtime = skill_runtime
        self.feedback_service = feedback_service
        self.improvement_service = improvement_service
        self.signal_pipeline = SignalPipeline()
        self.evidence_service = ProductizedEvidenceService()
        self.ranking_service = ProductizedRankingService()
        self.trend_event_service = ProductizedTrendEventService()
        self.quality_service = ProductizedQualityService()
        self.feedback_learning_service = ProductizedFeedbackLearningService(
            feedback_service=feedback_service,
            improvement_service=improvement_service,
        )
        self.improvement_workflow_service = ProductizedImprovementWorkflowService(
            improvement_service=improvement_service,
        )
        self.artifact_metadata_service = ProductizedArtifactMetadataService()

    def prepare_signals(self, request: dict[str, Any]) -> dict[str, Any]:
        run_id = run_id_from_request(request, self.board_type)
        context = analysis_context_from_request(self.board_type, request, run_id)
        raw_signals = list(request.get("signals") or [])
        pipeline_result = self.signal_pipeline.coerce_signals(
            raw_signals,
            context=context,
            board_type=self.board_type,
            topic=request.get("topic"),
        )
        skill_traces: list[dict[str, Any]] = []
        reliability_results = []
        for signal in pipeline_result.signals:
            source_result = self.skill_runtime.run_source_reliability(
                source_reliability_source_payload(signal),
                source_reliability_content_payload(signal),
                run_id=run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            reliability_results.append(source_result.output)
            skill_traces.append(source_result.to_dict())
        improvement_context = self.improvement_service.apply_approved_overrides(
            run_id=run_id,
            board_type=self.board_type.value,
        )
        run_state = ProductizedRunState.from_request(
            request=request,
            board_type=self.board_type,
            run_id=run_id,
        ).with_updates(
            skill_traces=skill_traces,
            source_reliability_results=reliability_results,
            improvement_context=improvement_context.to_dict(),
        )
        return {
            "context": context,
            "raw_signals": raw_signals,
            "prepared_signals": pipeline_result.signals,
            "source_reliability_results": reliability_results,
            "skill_traces": skill_traces,
            "improvement_context": improvement_context.to_dict(),
            "productized_run": run_state,
        }

    def classify_board_signals(self, *, context: AnalysisContext, prepared_signals: list[Any]) -> dict[str, Any]:
        return {"board_signals": self.board_service.select_signals(prepared_signals, context=context)}

    def extract_entities(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        extracted = []
        for signal in board_signals:
            result = self.skill_runtime.run_entity_extraction(
                signal_item_payload(signal),
                run_id=productized_run.run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            extracted.append({"signal_id": signal.signal_id, **result.output})
            skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            extracted_entities=extracted,
            skill_traces=skill_traces,
        )
        return {"extracted_entities": extracted, "skill_traces": skill_traces, "productized_run": run_state}

    def build_evidence(
        self,
        *,
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        bundle = self.evidence_service.build(
            board_signals,
            extracted_entities=productized_run.extracted_entities,
        )
        run_state = productized_run.with_updates(
            evidence_refs=bundle.refs,
            evidence_items=bundle.items,
        )
        return {
            "evidence_refs": bundle.refs,
            "evidence_items": bundle.items,
            "productized_run": run_state,
        }

    def deduplicate_events(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        items = [signal_item_payload(signal) for signal in board_signals]
        result = self.skill_runtime.run_event_deduplication(
            items,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            deduplication_result=result.output,
            skill_traces=skill_traces,
        )
        return {
            "deduplicated_signals": board_signals,
            "deduplication_result": result.output,
            "skill_traces": skill_traces,
            "productized_run": run_state,
        }

    def rank_items(self, *, deduplicated_signals: list[Any]) -> dict[str, Any]:
        return {"ranked_signals": self.ranking_service.rank(deduplicated_signals)}

    def analyze_trends(
        self,
        *,
        request: dict[str, Any],
        ranked_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        events = self.trend_event_service.build_events(
            productized_run.deduplication_result,
            ranked_signals,
        )
        result = self.skill_runtime.run_trend_analysis(
            events,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            trend_analysis=result.output,
            skill_traces=skill_traces,
        )
        return {"trend_analysis": result.output, "skill_traces": skill_traces, "productized_run": run_state}

    def build_board_output(
        self,
        *,
        request: dict[str, Any],
        context: AnalysisContext,
        ranked_signals: list[Any],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        result = self.board_service.build_board_run_result(ranked_signals, context=context)
        report_result = self.skill_runtime.run_report_writing(
            {
                "title": f"{self.board_service.board_definition.name} Summary",
                "audience": "subscriber",
                "style": "concise",
            },
            [card_report_item(card) for card in result.cards],
            trend_analyses=list(productized_run.trend_analysis.get("event_analyses", [])),
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces = [*productized_run.skill_traces, report_result.to_dict()]
        run_state = productized_run.with_updates(skill_traces=skill_traces)
        metadata = {**dict(result.metadata), **run_state.runtime_metadata()}
        result = result.model_copy(update={"metadata": metadata})
        board_output = dict(result.metadata.get("board_output") or {})
        board_output.setdefault("metadata", {})
        if isinstance(board_output["metadata"], dict):
            board_output["metadata"].update(
                {
                    "skill_trace_metadata": skill_traces,
                    "improvement_context": dict(run_state.improvement_context),
                    "trend_analysis": dict(run_state.trend_analysis),
                    "productized_run_state": run_state.to_dict(),
                }
            )
        return {
            "board_run_result": result,
            "board_output": board_output,
            "cards": [card.to_dict() for card in result.cards],
            "detail_pages": [page.to_dict() for page in result.detail_pages],
            "insights": [insight.to_dict() for insight in result.insights],
            "summary_md": report_result.output.get("markdown_report", summary_markdown(result)),
            "skill_traces": skill_traces,
            "productized_run": run_state,
        }

    def build_quality_summary(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        evidence_input = self.quality_service.evidence_check_input(
            board_run_result=board_run_result,
            evidence_items=productized_run.evidence_items,
            evidence_refs=productized_run.evidence_refs,
        )
        evidence_check = self.skill_runtime.run_evidence_checking(
            evidence_input.claims,
            evidence_input.sources,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(evidence_check.to_dict())
        quality = self.quality_service.merge_quality_summary(
            board_run_result=board_run_result,
            evidence_checking=evidence_check.output,
            skill_traces=skill_traces,
        )
        run_state = productized_run.with_updates(skill_traces=skill_traces)
        return {
            "quality_summary": quality,
            "evidence_checking": evidence_check.output,
            "skill_traces": skill_traces,
            "productized_run": run_state,
        }

    def build_subscription_payload(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        board_output: dict[str, Any],
        quality_summary: dict[str, Any],
    ) -> dict[str, Any]:
        quality_score = quality_summary.get("score") if isinstance(quality_summary, dict) else None
        payload = SubscriptionPayloadBuilder().build(
            run_id=run_id_from_request(request, self.board_type),
            board_type=self.board_type.value,
            topic=request.get("topic"),
            cards=board_run_result.cards,
            summary=str(board_output.get("metadata", {}).get("report", {}).get("summary") or f"{self.board_type.value} summary"),
            quality_score=float(quality_score) if quality_score is not None else None,
        )
        delivery_plan = DeliveryPlanBuilder().build(payload)
        return {"subscription_payload": {**payload.to_dict(), "delivery_plan": delivery_plan.to_dict()}}

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
        return {
            "artifact_metadata": self.artifact_metadata_service.build(
                board_type=self.board_type,
                request=request,
                cards=cards,
                quality_summary=quality_summary,
                subscription_payload=subscription_payload,
            )
        }


def analysis_context_from_request(board_type: BoardType, request: dict[str, Any], run_id: str) -> AnalysisContext:
    return AnalysisContext(
        run_context=RunContext(run_id=run_id, run_type="board_productized", profile="productized"),
        board_type=board_type,
        metadata={"topic": request.get("topic"), "productized": True},
        enable_llm=False,
    )


def run_id_from_request(request: dict[str, Any], board_type: BoardType) -> str:
    return str(request.get("run_id") or f"{board_type.value}-productized-run")


__all__ = ["ProductizedBoardUseCases", "analysis_context_from_request", "run_id_from_request"]
