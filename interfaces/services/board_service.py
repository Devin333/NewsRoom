from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import Field

from framework import RunResult

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._runner import runner_for_board_type
from business.boards._workflow import BoardWorkflowResult
from business.boards import (
    AINewsBoardService,
    CommunityPulseBoardService,
    CrossBoardService,
    PaperRadarBoardService,
    ProjectRadarBoardService,
)
from business.boards.ai_news.workflow import AINewsWorkflow
from business.boards.community_pulse.workflow import CommunityPulseWorkflow
from business.boards.cross_board import CrossBoardGraphIntelligenceResult
from business.boards.final_run_builder import FinalBusinessRunBuilder
from business.boards.paper_radar.workflow import PaperRadarWorkflow
from business.boards.project_radar.workflow import ProjectRadarWorkflow
from business.foundation import (
    AnalysisContext,
    BoardType,
    BusinessArtifactRef,
    BusinessFeedbackEvent,
    BusinessLearningSignal,
    BusinessPolicyCandidate,
    BusinessQualitySnapshot,
    BusinessRegressionGuardResult,
    PrimitiveModel,
    Report,
    Signal,
)
from business.foundation.subscription import SubscriptionPayloadBuilder
from business.boards.cross_board.intelligence_service import CrossBoardIntelligenceService
from business.layers.output import BoardOutput


PRIMARY_PRODUCTIZED_BOARD_TYPES = (
    BoardType.AI_NEWS,
    BoardType.PROJECT_RADAR,
    BoardType.PAPER_RADAR,
    BoardType.COMMUNITY_PULSE,
)
FORBIDDEN_PUBLIC_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
}


class BoardBuildResult(PrimitiveModel):
    board_type: BoardType
    output: BoardOutput


class CrossBoardBuildResult(PrimitiveModel):
    output: BoardOutput
    board_outputs: dict[str, BoardOutput] = Field(default_factory=dict)


class BoardWorkflowRunRequest(PrimitiveModel):
    board_type: BoardType
    items: list[Any] = Field(default_factory=list)
    context: AnalysisContext | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardWorkflowRunResponse(PrimitiveModel):
    board_type: BoardType
    workflow_result: BoardWorkflowResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraphRunRequest(PrimitiveModel):
    items: list[Any] = Field(default_factory=list)
    context: AnalysisContext | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossBoardGraphRunResponse(PrimitiveModel):
    result: CrossBoardGraphIntelligenceResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalBusinessRunResult(PrimitiveModel):
    board_workflow_results: dict[str, BoardWorkflowResult] = Field(default_factory=dict)
    cross_board_result: CrossBoardGraphIntelligenceResult
    cross_board_graph: Any
    cross_board_paths: list[Any] = Field(default_factory=list)
    cross_board_insights: list[Any] = Field(default_factory=list)
    policy_snapshot_refs: list[str] = Field(default_factory=list)
    quality_summary: BusinessQualitySnapshot
    feedback_events: list[BusinessFeedbackEvent] = Field(default_factory=list)
    learning_signals: list[BusinessLearningSignal] = Field(default_factory=list)
    policy_candidates: list[BusinessPolicyCandidate] = Field(default_factory=list)
    regression_guard_results: list[BusinessRegressionGuardResult] = Field(default_factory=list)
    artifacts: list[BusinessArtifactRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardApplicationService:
    def __init__(self) -> None:
        self._services = {
            BoardType.AI_NEWS: AINewsBoardService(),
            BoardType.PROJECT_RADAR: ProjectRadarBoardService(),
            BoardType.PAPER_RADAR: PaperRadarBoardService(),
            BoardType.COMMUNITY_PULSE: CommunityPulseBoardService(),
            BoardType.CROSS_BOARD: CrossBoardService(),
        }

    def list_boards(self) -> list[dict[str, Any]]:
        return [
            service.board_definition.to_dict()
            for service in self._services.values()
        ]

    def build_board_output(
        self,
        board_type: str | BoardType,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> BoardOutput:
        resolved_board_type = _board_type(board_type)
        resolved_context = _context_for_board(
            resolved_board_type,
            context=context,
            topic=topic,
        )
        return self._services[resolved_board_type].build_board_output(
            list(items),
            context=resolved_context,
        )

    def build_all_board_outputs(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> dict[str, BoardOutput]:
        outputs: dict[str, BoardOutput] = {}
        for board_type in (
            BoardType.AI_NEWS,
            BoardType.PROJECT_RADAR,
            BoardType.PAPER_RADAR,
            BoardType.COMMUNITY_PULSE,
        ):
            outputs[board_type.value] = self.build_board_output(
                board_type,
                items,
                topic=topic,
                context=context,
            )
        return outputs

    def build_cross_board_output(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> CrossBoardBuildResult:
        board_outputs = self.build_all_board_outputs(items, topic=topic, context=context)
        cross_board = self.build_board_output(
            BoardType.CROSS_BOARD,
            items,
            topic=topic,
            context=context,
        )
        return CrossBoardBuildResult(output=cross_board, board_outputs=board_outputs)

    def build_daily_digest(
        self,
        items: list[Any],
        *,
        topic: str | None = None,
        context: AnalysisContext | None = None,
    ) -> Report:
        output = self.build_board_output(
            BoardType.CROSS_BOARD,
            items,
            topic=topic,
            context=context,
        )
        report_payload = output.metadata.get("report")
        if not isinstance(report_payload, dict):
            raise ValueError("cross board output does not include a report payload")
        return Report.model_validate(report_payload)

    def attach_run_board_outputs(
        self,
        output: dict[str, Any],
        *,
        topic: str | None = None,
    ) -> None:
        items = _items_from_run_output(output)
        if not items:
            return
        cross_board_result = self.build_cross_board_output(items, topic=topic)
        output["board_outputs"] = {
            board_type: board_output.to_dict()
            for board_type, board_output in cross_board_result.board_outputs.items()
        }
        output["cross_board_output"] = cross_board_result.output.to_dict()

    def run_board(
        self,
        board_type: str,
        signals: list[dict],
        *,
        topic: str | None = None,
        run_id: str | None = None,
        artifact_root: str | Path = ".newsroom/runs",
    ) -> RunResult:
        resolved_board_type = _board_type(board_type)
        if resolved_board_type not in PRIMARY_PRODUCTIZED_BOARD_TYPES:
            raise ValueError(f"productized board run is not supported for {resolved_board_type.value}")
        return runner_for_board_type(
            resolved_board_type,
            artifact_root=artifact_root,
            board_service=self._services[resolved_board_type],
        ).run(signals=list(signals), topic=topic, run_id=run_id)

    def run_all_boards(
        self,
        signals: list[dict],
        *,
        topic: str | None = None,
        run_id_prefix: str | None = None,
        artifact_root: str | Path = ".newsroom/runs",
    ) -> dict[str, RunResult]:
        results: dict[str, RunResult] = {}
        for board_type in PRIMARY_PRODUCTIZED_BOARD_TYPES:
            run_id = f"{run_id_prefix}-{board_type.value}" if run_id_prefix else None
            results[board_type.value] = self.run_board(
                board_type.value,
                list(signals),
                topic=topic,
                run_id=run_id,
                artifact_root=artifact_root,
            )
        return results

    def build_productized_cross_board_output(
        self,
        signals: list[dict],
        *,
        topic: str | None = None,
        include_improvement: bool = True,
    ) -> dict[str, Any]:
        board_payloads = {
            board_type.value: _build_productized_board_payload(
                self._services[board_type],
                signals=list(signals),
                topic=topic,
            )
            for board_type in PRIMARY_PRODUCTIZED_BOARD_TYPES
        }
        return CrossBoardIntelligenceService().build(
            board_payloads,
            topic=topic,
            include_improvement=include_improvement,
        )


class BoardWorkflowApplicationService:
    def __init__(self) -> None:
        self._board_application = BoardApplicationService()
        self._workflows = {
            BoardType.AI_NEWS: AINewsWorkflow(),
            BoardType.PROJECT_RADAR: ProjectRadarWorkflow(),
            BoardType.PAPER_RADAR: PaperRadarWorkflow(),
            BoardType.COMMUNITY_PULSE: CommunityPulseWorkflow(),
        }
        self._cross_board_service = CrossBoardService()
        self._final_run_builder = FinalBusinessRunBuilder(FinalBusinessRunResult)

    def run_board_workflow(
        self,
        board_type: str | BoardType,
        items: list[Any],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardWorkflowRunResponse:
        resolved_board_type = _board_type(board_type)
        if resolved_board_type not in self._workflows:
            raise ValueError(f"board workflow is not supported for {resolved_board_type.value}")
        workflow_context = _context_for_board(resolved_board_type, context=context, topic=None)
        result = self._workflows[resolved_board_type].run(list(items), context=workflow_context)
        return BoardWorkflowRunResponse(
            board_type=resolved_board_type,
            workflow_result=result,
            metadata={"board_focus": result.metadata.get("board_focus")},
        )

    def run_all_board_workflows(
        self,
        items: list[Any],
        *,
        context: AnalysisContext | None = None,
    ) -> dict[str, BoardWorkflowResult]:
        results: dict[str, BoardWorkflowResult] = {}
        for board_type in (
            BoardType.AI_NEWS,
            BoardType.PROJECT_RADAR,
            BoardType.PAPER_RADAR,
            BoardType.COMMUNITY_PULSE,
        ):
            results[board_type.value] = self.run_board_workflow(board_type, items, context=context).workflow_result
        return results

    def run_cross_board_graph_intelligence(
        self,
        items: list[Any],
        *,
        context: AnalysisContext | None = None,
    ) -> CrossBoardGraphRunResponse:
        resolved_context = _context_for_board(BoardType.CROSS_BOARD, context=context, topic=None)
        result = self._cross_board_service.build_graph_intelligence(list(items), context=resolved_context)
        return CrossBoardGraphRunResponse(
            result=result,
            metadata={
                "path_count": len(result.paths),
                "insight_count": len(result.insights),
            },
        )

    def build_final_business_run(
        self,
        items: list[Any],
        *,
        context: AnalysisContext | None = None,
    ) -> FinalBusinessRunResult:
        workflow_results = self.run_all_board_workflows(items, context=context)
        cross_board_response = self.run_cross_board_graph_intelligence(items, context=context)
        return self._final_run_builder.build(workflow_results, cross_board_response.result)


def _board_type(value: str | BoardType) -> BoardType:
    if isinstance(value, BoardType):
        return value
    normalized = str(value).strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("board_type is required")
    try:
        return BoardType(normalized)
    except ValueError as exc:
        valid = ", ".join(board_type.value for board_type in BoardType)
        raise ValueError(f"unsupported board_type: {value}; expected one of: {valid}") from exc


def _context_for_board(
    board_type: BoardType,
    *,
    context: AnalysisContext | None,
    topic: str | None,
) -> AnalysisContext:
    metadata = dict(context.metadata if context is not None else {})
    if topic:
        metadata["topic"] = topic
    if context is None:
        return AnalysisContext(board_type=board_type, metadata=metadata)
    return context.for_board(board_type).model_copy(update={"metadata": metadata})


def _items_from_run_output(output: dict[str, Any]) -> list[Any]:
    for key in ("signals", "ranked_items", "normalized_items", "raw_items"):
        value = output.get(key)
        if isinstance(value, list):
            if key == "ranked_items":
                return [_ranked_item_payload(item) for item in value]
            if key == "normalized_items":
                return [_normalized_item_payload(item) for item in value]
            return value
    evidence_bundle = output.get("evidence_bundle")
    evidence_items = _field_value(evidence_bundle, "items", default=None)
    if isinstance(evidence_items, list):
        return [_item_from_evidence(item) for item in evidence_items]
    return []


def _build_productized_board_payload(
    service: Any,
    *,
    signals: list[dict],
    topic: str | None,
) -> dict[str, Any]:
    context = _context_for_board(service.board_type, context=None, topic=topic)
    result = service.build_board_run_result(list(signals), context=context)
    board_output = dict(result.metadata.get("board_output") or {})
    cards = [card.to_dict() for card in result.cards]
    detail_pages = [page.to_dict() for page in result.detail_pages]
    insights = [insight.to_dict() for insight in result.insights]
    quality_summary = result.quality_summary.to_dict() if result.quality_summary is not None else {"status": "unchecked", "score": None}
    report = board_output.get("metadata", {}).get("report", {}) if isinstance(board_output.get("metadata"), dict) else {}
    summary = str(report.get("summary") or f"{service.board_type.value} summary")
    quality_score = quality_summary.get("score") if isinstance(quality_summary, dict) else None
    subscription = SubscriptionPayloadBuilder().build(
        run_id=result.run_id,
        board_type=service.board_type.value,
        topic=topic,
        cards=result.cards,
        summary=summary,
        quality_score=float(quality_score) if quality_score is not None else None,
    )
    feedback_service = BoardFeedbackService()
    improvement_service = BoardImprovementService()
    feedback_events = improvement_service.collect_feedback(
        feedback_service.collect(board_run_result=result, quality_summary=result.quality_summary)
    )
    learning_signals = improvement_service.build_learning_signals(feedback_events)
    recommendations = improvement_service.build_recommendations(
        learning_signals,
        board_type=service.board_type.value,
        quality_summary=quality_summary,
    )
    proposals = improvement_service.build_proposals(recommendations)
    improvement_context = improvement_service.apply_approved_overrides(
        run_id=result.run_id,
        board_type=service.board_type.value,
    )
    measurement = improvement_service.measure(
        None,
        {
            "quality_score": quality_score,
            "card_count": len(cards),
            "evidence_coverage": _card_evidence_coverage(cards),
            "duplicate_rate": 0.0,
            "empty_output": len(cards) == 0,
            "subscription_match": 1.0 if subscription.targets else 0.0,
        },
    )
    report_payload = improvement_service.build_report(
        feedback_events=feedback_events,
        learning_signals=learning_signals,
        recommendations=recommendations,
        proposals=proposals,
        applied_overrides=improvement_context.applied_overrides,
        measurement=measurement,
    )
    return {
        "board_output": board_output,
        "cards": cards,
        "detail_pages": detail_pages,
        "insights": insights,
        "quality_summary": quality_summary,
        "subscription_payload": subscription.to_dict(),
        "feedback_events": [event.to_dict() for event in feedback_events],
        "learning_signals": [signal.to_dict() for signal in learning_signals],
        "improvement_recommendations": [recommendation.to_dict() for recommendation in recommendations],
        "improvement_proposals": [proposal.to_dict() for proposal in proposals],
        "applied_overrides": improvement_context.applied_overrides,
        "improvement_measurement": measurement.to_dict(),
        "self_improvement_report": report_payload.to_dict(),
    }


def _card_evidence_coverage(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    return round(sum(1 for card in cards if card.get("evidence_refs")) / len(cards), 4)


def _item_from_evidence(item: Any) -> dict[str, Any]:
    if isinstance(item, Signal):
        payload = item.to_dict()
    elif hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    summary = payload.get("summary") or payload.get("text") or payload.get("description")
    content_excerpt = _content_excerpt(
        payload.get("content")
        or payload.get("sanitized_content")
        or payload.get("content_excerpt")
        or payload.get("raw_content")
        or payload.get("raw_html")
        or payload.get("full_text")
        or summary
    )
    metadata = _sanitize_public_payload(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "source_item_id",
                "evidence_id",
                "id",
                "source_id",
                "source",
                "source_name",
                "source_type",
                "title",
                "headline",
                "url",
                "source_url",
                "fetched_at",
                "collected_at",
                "published_at",
                "summary",
                "text",
                "description",
                "content",
                "sanitized_content",
                "content_excerpt",
                "authors",
                "tags",
                "language",
            }
        }
    )
    if content_excerpt:
        metadata.setdefault("content_excerpt", content_excerpt)
    result = {
        "source_item_id": str(payload.get("source_item_id") or payload.get("evidence_id") or payload.get("id") or payload.get("title") or "evidence"),
        "source_id": str(payload.get("source_id") or source.get("source_id") or payload.get("source_name") or "evidence"),
        "source_name": str(payload.get("source_name") or source.get("source_name") or payload.get("source_id") or "Evidence"),
        "source_type": str(payload.get("source_type") or source.get("source_type") or "manual"),
        "title": str(payload.get("title") or payload.get("headline") or summary or "Evidence item"),
        "url": str(payload.get("source_url") or payload.get("url") or source.get("source_url") or source.get("url") or "manual://evidence"),
        "fetched_at": payload.get("fetched_at") or payload.get("collected_at"),
        "published_at": payload.get("published_at"),
        "summary": summary or content_excerpt,
        "authors": payload.get("authors") or [],
        "tags": payload.get("tags") or [],
        "language": payload.get("language"),
        "metadata": metadata,
    }
    if content_excerpt:
        result["content_excerpt"] = content_excerpt
    return result


def _sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in FORBIDDEN_PUBLIC_FIELD_NAMES:
                continue
            cleaned[key] = _sanitize_public_payload(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_public_payload(item) for item in value]
    return value


def _content_excerpt(value: Any, *, max_length: int = 500) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def _ranked_item_payload(item: Any) -> Any:
    if is_dataclass(item):
        payload = asdict(cast(Any, item))
    elif hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    if isinstance(payload.get("item"), dict):
        return payload["item"]
    return payload


def _normalized_item_payload(item: Any) -> Any:
    if is_dataclass(item):
        payload = asdict(cast(Any, item))
    elif hasattr(item, "to_dict"):
        payload = item.to_dict()
    elif isinstance(item, dict):
        payload = dict(item)
    else:
        payload = {}
    return payload


def _field_value(value: Any, name: str, *, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
