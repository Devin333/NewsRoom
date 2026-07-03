from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from business.foundation import AnalysisContext, BoardType, BoardCard, Relation, ReportType, Signal
from business.layers.analysis.pipeline import AnalysisResult
from business.layers.extraction.models import ExtractionResult
from business.layers.output.board_card_builder import BoardCardBuilder
from business.layers.output.detail_page_builder import DetailBuildContext, DetailPageBuilder
from business.layers.output.insight_builder import InsightBuilder
from business.layers.output.models import BoardOutput, BoardOutputSection, BoardOutputStats
from business.layers.output.report_builder import ReportBuilder
from business.layers.output.section_composer import SectionComposer


class ReportContextProvider(Protocol):
    def build_context(self, request: Any) -> Any: ...


@dataclass(frozen=True)
class ReportContextRequest:
    topic: str
    run_id: str | None = None
    entity_ids: list[str] | None = None
    limit: int = 8


class BoardOutputPipeline:
    def __init__(
        self,
        *,
        card_builder: BoardCardBuilder | None = None,
        detail_builder: DetailPageBuilder | None = None,
        insight_builder: InsightBuilder | None = None,
        report_builder: ReportBuilder | None = None,
        section_composer: SectionComposer | None = None,
        report_context_provider: ReportContextProvider | None = None,
    ) -> None:
        self.card_builder = card_builder or BoardCardBuilder()
        self.detail_builder = detail_builder or DetailPageBuilder()
        self.insight_builder = insight_builder or InsightBuilder()
        self.report_builder = report_builder or ReportBuilder()
        self.section_composer = section_composer or SectionComposer()
        self.report_context_provider = report_context_provider

    def build_board_output(
        self,
        board_type: BoardType,
        signals: list[Signal],
        extractions: list[ExtractionResult],
        relations: list[Relation],
        analysis: AnalysisResult,
        context: AnalysisContext,
    ) -> BoardOutput:
        cards: list[BoardCard] = []
        detail_pages = []
        extraction_by_signal = {item.signal_id: item for item in extractions}

        for signal in signals:
            extraction = extraction_by_signal.get(signal.signal_id)
            if extraction is None:
                continue
            signal_relations = _relations_for_signal(signal, relations)
            card = self.card_builder.build_card(signal, extraction, signal_relations, analysis, board_type)
            cards.append(card)
            detail_pages.append(
                self.detail_builder.build_detail_page(
                    card.primary_object_ref,
                    DetailBuildContext(
                        board_type=board_type,
                        related_cards=[card],
                        related_insights=[],
                        analysis=analysis,
                        metadata={"signal_id": signal.signal_id},
                    ),
                )
            )

        insights = self.insight_builder.build_insights(board_type, signals, extractions, relations, analysis, context)
        report_type = ReportType.CROSS_BOARD if board_type == BoardType.CROSS_BOARD else ReportType.BOARD
        retrieved_context = self._build_report_context(board_type, context)
        report = self.report_builder.build_report(
            board_type,
            cards,
            insights,
            detail_pages,
            analysis.radar_items,
            report_type=report_type,
            retrieved_context=retrieved_context,
        )
        metadata = {"report": report.to_dict(), "context": context.to_dict()}
        if retrieved_context is not None:
            metadata["rag_context"] = dict(retrieved_context)
        return BoardOutput(
            board_type=board_type,
            cards=cards,
            insights=insights,
            detail_pages=detail_pages,
            radar_items=list(analysis.radar_items),
            stats=BoardOutputStats(
                signal_count=len(signals),
                card_count=len(cards),
                detail_page_count=len(detail_pages),
                insight_count=len(insights),
                relation_count=len(relations),
                radar_item_count=len(analysis.radar_items),
            ),
            sections=self.section_composer.from_report(report),
            metadata=metadata,
        )

    def _build_report_context(
        self,
        board_type: BoardType,
        context: AnalysisContext,
    ) -> dict[str, Any] | None:
        if self.report_context_provider is None:
            return None
        topic = _report_context_topic(board_type, context)
        request = ReportContextRequest(
            topic=topic,
            run_id=context.run_context.run_id if context.run_context else None,
            entity_ids=_string_list(context.metadata.get("entity_ids")),
            limit=_context_limit(context.metadata.get("report_memory_limit")),
        )
        try:
            result = self.report_context_provider.build_context(request)
        except Exception as exc:
            return {
                "topic": topic,
                "prompt_context": "",
                "context": {
                    "query": topic,
                    "metadata": {
                        "memory_available": False,
                        "reason": f"report_context_failed:{type(exc).__name__}",
                    },
                },
            }
        if callable(getattr(result, "to_dict", None)):
            payload = result.to_dict()
            return dict(payload) if isinstance(payload, dict) else None
        return dict(result) if isinstance(result, dict) else None


def _relations_for_signal(signal: Signal, relations: list[Relation]) -> list[Relation]:
    return [
        relation
        for relation in relations
        if relation.source_ref.object_id == signal.signal_id or relation.target_ref.object_id == signal.signal_id
    ]


def _report_context_topic(board_type: BoardType, context: AnalysisContext) -> str:
    for key in ("report_topic", "topic", "memory_topic"):
        value = context.metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    if context.run_context is not None:
        for key in ("report_topic", "topic", "memory_topic"):
            value = context.run_context.options.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return board_type.value.replace("_", " ")


def _context_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 8
    return max(1, min(20, limit))


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    try:
        values = [str(item).strip() for item in value if str(item).strip()]
    except TypeError:
        text = str(value).strip()
        return [text] if text else None
    return values or None


__all__ = [
    "BoardOutput",
    "BoardOutputPipeline",
    "BoardOutputSection",
    "BoardOutputStats",
    "DetailBuildContext",
    "DetailPageBuilder",
    "InsightBuilder",
    "ReportBuilder",
    "ReportContextProvider",
    "ReportContextRequest",
    "BoardCardBuilder",
]
