from __future__ import annotations

from business.foundation import AnalysisContext, BoardType, BoardCard, Relation, ReportType, Signal
from business.layers.analysis.pipeline import AnalysisResult
from business.layers.extraction.models import ExtractionResult
from business.layers.output.board_card_builder import BoardCardBuilder
from business.layers.output.detail_page_builder import DetailBuildContext, DetailPageBuilder
from business.layers.output.insight_builder import InsightBuilder
from business.layers.output.models import BoardOutput, BoardOutputSection, BoardOutputStats
from business.layers.output.report_builder import ReportBuilder
from business.layers.output.section_composer import SectionComposer


class BoardOutputPipeline:
    def __init__(
        self,
        *,
        card_builder: BoardCardBuilder | None = None,
        detail_builder: DetailPageBuilder | None = None,
        insight_builder: InsightBuilder | None = None,
        report_builder: ReportBuilder | None = None,
        section_composer: SectionComposer | None = None,
    ) -> None:
        self.card_builder = card_builder or BoardCardBuilder()
        self.detail_builder = detail_builder or DetailPageBuilder()
        self.insight_builder = insight_builder or InsightBuilder()
        self.report_builder = report_builder or ReportBuilder()
        self.section_composer = section_composer or SectionComposer()

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
        report = self.report_builder.build_report(
            board_type,
            cards,
            insights,
            detail_pages,
            analysis.radar_items,
            report_type=report_type,
        )
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
            metadata={"report": report.to_dict(), "context": context.to_dict()},
        )


def _relations_for_signal(signal: Signal, relations: list[Relation]) -> list[Relation]:
    return [
        relation
        for relation in relations
        if relation.source_ref.object_id == signal.signal_id or relation.target_ref.object_id == signal.signal_id
    ]


__all__ = [
    "BoardOutput",
    "BoardOutputPipeline",
    "BoardOutputSection",
    "BoardOutputStats",
    "DetailBuildContext",
    "DetailPageBuilder",
    "InsightBuilder",
    "ReportBuilder",
    "BoardCardBuilder",
]
