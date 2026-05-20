from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from business.foundation import (
    AnalysisContext,
    Badge,
    BoardCard,
    BoardType,
    Claim,
    Confidence,
    DetailPage,
    DetailSection,
    DetailSectionType,
    DisplayMetric,
    Insight,
    InsightType,
    MaturityStage,
    ObjectRef,
    ObjectType,
    Report,
    ReportSection,
    ReportType,
    Relation,
    RadarRecommendation,
    Signal,
    Score,
    Technology,
    TimeWindow,
    TrendDirection,
    build_stable_id,
)
from business.foundation.primitives import PrimitiveModel
from business.layers.analysis.pipeline import AnalysisResult, TechnologyRadarItem
from business.layers.extraction.models import ExtractionResult


class DetailBuildContext(PrimitiveModel):
    board_type: BoardType
    related_cards: list[BoardCard] = Field(default_factory=list)
    related_insights: list[Insight] = Field(default_factory=list)
    analysis: AnalysisResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardOutputSection(PrimitiveModel):
    title: str
    section_type: DetailSectionType
    content: str | None = None
    cards: list[BoardCard] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    metrics: list[DisplayMetric] = Field(default_factory=list)


class BoardOutputStats(PrimitiveModel):
    signal_count: int
    card_count: int
    detail_page_count: int
    insight_count: int
    relation_count: int
    radar_item_count: int


class BoardOutput(PrimitiveModel):
    board_type: BoardType
    cards: list[BoardCard] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    detail_pages: list[DetailPage] = Field(default_factory=list)
    radar_items: list[TechnologyRadarItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stats: BoardOutputStats
    sections: list[BoardOutputSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoardCardBuilder:
    def build_card(
        self,
        signal: Signal,
        extraction: ExtractionResult,
        relations: list[Relation],
        analysis: AnalysisResult,
        board_type: BoardType,
    ) -> BoardCard:
        primary = _primary_object(signal, extraction)
        score = _board_score(signal, extraction, relations, analysis)
        badges = _badges(signal, extraction, analysis)
        metrics = _metrics(signal, extraction, relations, analysis)
        related_refs = _related_refs(signal, extraction, relations)
        return BoardCard(
            card_id=build_stable_id("card", board_type.value, primary.object_id),
            board_type=board_type,
            title=_card_title(signal, extraction),
            subtitle=_card_subtitle(signal),
            summary=_card_summary(signal, extraction),
            primary_object_ref=primary,
            badges=badges,
            metrics=metrics,
            related_refs=related_refs,
            score=score,
            confidence=_card_confidence(signal, extraction, relations),
            published_at=signal.published_at,
            metadata={"signal_id": signal.signal_id, "board_type": board_type.value},
        )


class DetailPageBuilder:
    def build_detail_page(
        self,
        primary_ref: ObjectRef,
        context: DetailBuildContext,
    ) -> DetailPage:
        analysis = context.analysis
        board_type = context.board_type
        sections: list[DetailSection] = []
        if analysis is not None:
            sections.append(
                DetailSection(
                    title="Summary",
                    section_type=DetailSectionType.SUMMARY,
                    content=f"Detail page for {primary_ref.label or primary_ref.object_id}.",
                )
            )
            if analysis.radar_items:
                sections.append(
                    DetailSection(
                        title="Technology Radar",
                        section_type=DetailSectionType.TECHNOLOGY_RADAR,
                        content="Radar snapshot generated from analysis.",
                    )
                )
        return DetailPage(
            page_id=build_stable_id("page", board_type.value, primary_ref.object_id),
            board_type=board_type,
            title=primary_ref.label or primary_ref.object_id,
            summary=f"Details for {primary_ref.label or primary_ref.object_id}",
            primary_object_ref=primary_ref,
            sections=sections,
            related_cards=list(context.related_cards),
            insights=list(context.related_insights),
            metadata=context.metadata,
        )


class InsightBuilder:
    def build_insights(
        self,
        board_type: BoardType,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        analysis: AnalysisResult,
        context: AnalysisContext,
    ) -> list[Insight]:
        insights: list[Insight] = []
        for radar_item in analysis.radar_items:
            if radar_item.recommendation in {RadarRecommendation.HIGH_PRIORITY, RadarRecommendation.INVESTIGATE}:
                insights.append(
                    Insight(
                        insight_id=build_stable_id("insight", board_type.value, radar_item.technology_ref.object_id, radar_item.recommendation.value),
                        title=f"{radar_item.name} is worth {radar_item.recommendation.value.replace('_', ' ')}",
                        summary=f"{radar_item.name} shows {radar_item.trend_direction.value} trend and {radar_item.maturity_stage.value} maturity.",
                        insight_type=InsightType.TECHNOLOGY_EMERGENCE,
                        related_object_refs=[radar_item.technology_ref],
                        evidence_relation_ids=list(radar_item.key_relations),
                        time_window=_analysis_time_window(signals, context),
                        confidence=Confidence(value=min(1.0, radar_item.trend_score.value + 0.1), factors=list(radar_item.trend_score.factors)),
                        importance=Score(value=min(1.0, radar_item.impact_score.value), factors=list(radar_item.impact_score.factors)),
                        metadata={"recommendation": radar_item.recommendation.value},
                    )
                )
        return insights


class ReportBuilder:
    def build_report(
        self,
        board_type: BoardType,
        cards: list[BoardCard],
        insights: list[Insight],
        detail_pages: list[DetailPage],
        radar_items: list[TechnologyRadarItem],
        *,
        report_type: ReportType = ReportType.BOARD,
        title: str | None = None,
        summary: str | None = None,
    ) -> Report:
        sections = [
            ReportSection(
                title="Top Cards",
                section_type=DetailSectionType.KEY_POINTS,
                cards=list(cards),
                related_refs=[card.primary_object_ref for card in cards],
            ),
            ReportSection(
                title="Insights",
                section_type=DetailSectionType.EVIDENCE,
                insights=list(insights),
                related_refs=[ref for insight in insights for ref in insight.related_object_refs],
            ),
        ]
        if radar_items:
            sections.append(
                ReportSection(
                    title="Technology Radar",
                    section_type=DetailSectionType.TECHNOLOGY_RADAR,
                    related_refs=[item.technology_ref for item in radar_items],
                )
            )
        return Report(
            report_id=build_stable_id("report", board_type.value, report_type.value, title or board_type.value),
            report_type=report_type,
            board_type=board_type,
            title=title or f"{board_type.value.replace('_', ' ').title()} Report",
            summary=summary or f"Report for {board_type.value}",
            sections=sections,
            insights=list(insights),
            cards=list(cards),
            detail_pages=list(detail_pages),
            metadata={"board_type": board_type.value},
        )


class BoardOutputPipeline:
    def build_board_output(
        self,
        board_type: BoardType,
        signals: list[Signal],
        extractions: list[ExtractionResult],
        relations: list[Relation],
        analysis: AnalysisResult,
        context: AnalysisContext,
    ) -> BoardOutput:
        card_builder = BoardCardBuilder()
        detail_builder = DetailPageBuilder()
        insight_builder = InsightBuilder()
        report_builder = ReportBuilder()
        cards: list[BoardCard] = []
        detail_pages: list[DetailPage] = []
        for signal in signals:
            extraction = next((item for item in extractions if item.signal_id == signal.signal_id), None)
            if extraction is None:
                continue
            signal_relations = [relation for relation in relations if relation.source_ref.object_id == signal.signal_id or relation.target_ref.object_id == signal.signal_id]
            card = card_builder.build_card(signal, extraction, signal_relations, analysis, board_type)
            cards.append(card)
            detail_pages.append(
                detail_builder.build_detail_page(
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
        insights = insight_builder.build_insights(board_type, signals, extractions, relations, analysis, context)
        report_type = ReportType.CROSS_BOARD if board_type == BoardType.CROSS_BOARD else ReportType.BOARD
        report = report_builder.build_report(
            board_type,
            cards,
            insights,
            detail_pages,
            analysis.radar_items,
            report_type=report_type,
        )
        sections = [
            BoardOutputSection(
                title=section.title,
                section_type=section.section_type,
                content=section.content,
                cards=list(section.cards),
                relations=list(getattr(section, "relations", [])),
                metrics=list(section.metrics),
            )
            for section in report.sections
        ]
        stats = BoardOutputStats(
            signal_count=len(signals),
            card_count=len(cards),
            detail_page_count=len(detail_pages),
            insight_count=len(insights),
            relation_count=len(relations),
            radar_item_count=len(analysis.radar_items),
        )
        return BoardOutput(
            board_type=board_type,
            cards=cards,
            insights=insights,
            detail_pages=detail_pages,
            radar_items=list(analysis.radar_items),
            stats=stats,
            sections=sections,
            metadata={"report": report.to_dict(), "context": context.to_dict()},
        )


def _analysis_time_window(signals: list[Signal], context: AnalysisContext) -> TimeWindow:
    if not signals:
        return context.time_window
    published = [signal.published_at for signal in signals if signal.published_at is not None]
    if not published:
        return context.time_window
    start = min(published)
    end = max(published)
    return TimeWindow(start_at=start, end_at=end, label="board_signals")


def _primary_object(signal: Signal, extraction: ExtractionResult) -> ObjectRef:
    if extraction.technologies:
        technology = extraction.technologies[0]
        return ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name)
    if extraction.entities:
        entity = extraction.entities[0]
        return ObjectRef(object_type="entity", object_id=entity.entity_id, label=entity.canonical_name)
    if extraction.topics:
        topic = extraction.topics[0]
        return ObjectRef(object_type="topic", object_id=topic.topic_id, label=topic.name)
    return ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title)


def _card_title(signal: Signal, extraction: ExtractionResult) -> str:
    primary = _primary_object(signal, extraction)
    return primary.label or signal.title


def _card_subtitle(signal: Signal) -> str:
    parts = [signal.source.source_name]
    if signal.published_at:
        parts.append(signal.published_at.isoformat())
    return " · ".join(parts)


def _card_summary(signal: Signal, extraction: ExtractionResult) -> str:
    return signal.summary or signal.content or signal.title


def _card_confidence(signal: Signal, extraction: ExtractionResult, relations: list[Relation]) -> Confidence:
    base = signal.confidence.value if signal.confidence else 0.6
    relation_boost = min(0.2, len(relations) * 0.02)
    extraction_boost = min(0.1, (len(extraction.entities) + len(extraction.technologies)) * 0.02)
    return Confidence(value=min(1.0, base + relation_boost + extraction_boost), factors=list(signal.confidence.factors) if signal.confidence else [])


def _badges(signal: Signal, extraction: ExtractionResult, analysis: AnalysisResult) -> list[Badge]:
    badges = [Badge(label=signal.board_type.value), Badge(label=signal.signal_type.value)]
    if analysis.radar_items:
        badges.append(Badge(label=analysis.radar_items[0].recommendation.value.replace("_", " ")))
    if extraction.technologies:
        badges.append(Badge(label=extraction.technologies[0].category.value))
    return badges


def _metrics(signal: Signal, extraction: ExtractionResult, relations: list[Relation], analysis: AnalysisResult) -> list[DisplayMetric]:
    return [
        DisplayMetric(label="Relations", value=len(relations)),
        DisplayMetric(label="Technologies", value=len(extraction.technologies)),
        DisplayMetric(label="Signals", value=1),
    ]


def _related_refs(signal: Signal, extraction: ExtractionResult, relations: list[Relation]) -> list[ObjectRef]:
    refs = [relation.target_ref for relation in relations]
    if extraction.technologies:
        refs.extend(ObjectRef(object_type="technology", object_id=item.technology_id, label=item.name) for item in extraction.technologies)
    return _dedupe_refs(refs)


def _board_score(signal: Signal, extraction: ExtractionResult, relations: list[Relation], analysis: AnalysisResult) -> Score:
    trend = next((item for item in analysis.trends if item.target_ref.object_id in {technology.technology_id for technology in extraction.technologies}), None)
    quality = next((item for item in analysis.qualities if item.target_ref.object_id == signal.signal_id), None)
    impact = next((item for item in analysis.impacts if item.target_ref.object_id in {technology.technology_id for technology in extraction.technologies}), None)
    value = 0.4
    factors = []
    if trend is not None:
        value += 0.2 * trend.score.value
        factors.extend(trend.score.factors)
    if quality is not None:
        value += 0.2 * quality.score.value
        factors.extend(quality.score.factors)
    if impact is not None:
        value += 0.2 * impact.score.value
        factors.extend(impact.score.factors)
    return Score(value=min(1.0, round(value, 4)), factors=factors)


def _dedupe_refs(refs: list[ObjectRef]) -> list[ObjectRef]:
    seen: set[tuple[str, str]] = set()
    result: list[ObjectRef] = []
    for ref in refs:
        marker = (ObjectType(ref.object_type).value, ref.object_id)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(ref)
    return result
