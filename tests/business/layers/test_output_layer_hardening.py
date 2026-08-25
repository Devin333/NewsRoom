from __future__ import annotations

from datetime import UTC, datetime

from business.foundation import (
    AnalysisContext,
    BoardType,
    Confidence,
    Impact,
    ImpactArea,
    Maturity,
    MaturityStage,
    ObjectRef,
    Quality,
    RadarRecommendation,
    Relation,
    RelationDirection,
    RelationType,
    Score,
    ScoreFactor,
    Signal,
    SignalType,
    SourceRef,
    SourceReliability,
    SourceType,
    Technology,
    TechnologyCategory,
    TimeWindow,
    Trend,
    TrendDirection,
)
from business.foundation.context import RunContext
from business.layers.analysis.pipeline import AnalysisResult, TechnologyRadarItem
from business.layers.extraction.models import ExtractionResult
from business.layers.output import BoardOutputPipeline
from business.layers.output.board_card_builder import BoardCardBuilder
from business.layers.output.detail_page_builder import DetailBuildContext, DetailPageBuilder
from business.layers.output.insight_builder import InsightBuilder
from business.layers.output.report_builder import ReportBuilder
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory
from business.memory.report_memory_context import ReportMemoryContextResult


def test_board_card_serializes_without_raw_payload_and_keeps_output_contract() -> None:
    signal, extraction, relations, analysis, context = _pipeline_inputs()

    output = BoardOutputPipeline().build_board_output(
        BoardType.AI_NEWS,
        [signal],
        [extraction],
        relations,
        analysis,
        context,
    )

    card = output.cards[0]
    serialized = card.to_dict()
    assert "raw_payload" not in serialized
    assert card.evidence_refs
    assert card.provenance is not None
    assert "workflow_id" not in serialized["provenance"]
    assert card.quality is not None
    assert card.ranking_reason


def test_detail_page_and_report_have_sections_cards_and_insights() -> None:
    signal, extraction, relations, analysis, context = _pipeline_inputs()
    card = BoardCardBuilder().build_card(signal, extraction, relations, analysis, BoardType.AI_NEWS)
    insights = InsightBuilder().build_insights(BoardType.AI_NEWS, [signal], [extraction], relations, analysis, context)
    detail = DetailPageBuilder().build_detail_page(
        card.primary_object_ref,
        DetailBuildContext(
            board_type=BoardType.AI_NEWS,
            related_cards=[card],
            related_insights=insights,
            analysis=analysis,
        ),
    )
    report = ReportBuilder().build_report(BoardType.AI_NEWS, [card], insights, [detail], analysis.radar_items)

    assert detail.sections
    assert report.cards == [card]
    assert report.insights == insights
    assert report.sections


def test_board_output_pipeline_runs_with_split_builders() -> None:
    signal, extraction, relations, analysis, context = _pipeline_inputs()

    output = BoardOutputPipeline().build_board_output(
        BoardType.AI_NEWS,
        [signal],
        [extraction],
        relations,
        analysis,
        context,
    )

    assert output.cards
    assert output.detail_pages
    assert output.insights
    assert output.sections
    assert output.stats.signal_count == 1
    assert output.stats.card_count == 1
    assert output.stats.detail_page_count == 1
    assert output.stats.insight_count == 1
    assert output.metadata["report"]["cards"]
    assert output.metadata["report"]["insights"]
    assert output.metadata["report"]["sections"]
    assert "rag_context" not in output.metadata["report"]["metadata"]
    assert all(section["title"] != "Retrieved Context" for section in output.metadata["report"]["sections"])


def test_board_output_pipeline_projects_report_memory_context_into_report() -> None:
    signal, extraction, relations, analysis, _ = _pipeline_inputs()
    provider = _FakeReportContextProvider()
    context = AnalysisContext(
        board_type=BoardType.AI_NEWS,
        run_context=RunContext(
            run_id="run-daily-1",
            run_type="daily",
            options={"topic": "AI agents"},
        ),
        metadata={"report_memory_limit": 2},
    )

    output = BoardOutputPipeline(report_context_provider=provider).build_board_output(
        BoardType.AI_NEWS,
        [signal],
        [extraction],
        relations,
        analysis,
        context,
    )

    [request] = provider.requests
    assert request.topic == "AI agents"
    assert request.run_id == "run-daily-1"
    assert request.limit == 2
    report = output.metadata["report"]
    assert report["metadata"]["rag_context"]["topic"] == "AI agents"
    assert report["metadata"]["rag_context"]["context"]["claims"][0]["text"] == "Known historical claim"
    retrieved_section = next(section for section in report["sections"] if section["title"] == "Retrieved Context")
    assert "Known claims:" in retrieved_section["content"]
    assert any(section.title == "Retrieved Context" for section in output.sections)
    assert output.metadata["rag_context"]["topic"] == "AI agents"


def test_board_output_pipeline_records_report_context_failure_without_failing_report() -> None:
    signal, extraction, relations, analysis, context = _pipeline_inputs()

    output = BoardOutputPipeline(report_context_provider=_FailingReportContextProvider()).build_board_output(
        BoardType.AI_NEWS,
        [signal],
        [extraction],
        relations,
        analysis,
        context,
    )

    report = output.metadata["report"]
    assert report["cards"]
    rag_context = report["metadata"]["rag_context"]
    assert rag_context["topic"] == "ai news"
    assert rag_context["context"]["metadata"]["memory_available"] is False
    assert rag_context["context"]["metadata"]["reason"] == "report_context_failed:RuntimeError"
    assert all(section["title"] != "Retrieved Context" for section in report["sections"])


def _pipeline_inputs() -> tuple[Signal, ExtractionResult, list[Relation], AnalysisResult, AnalysisContext]:
    published = datetime(2026, 5, 19, tzinfo=UTC)
    source = SourceRef(
        source_name="OpenAI Blog",
        source_type=SourceType.OFFICIAL_BLOG,
        url="https://example.com/agent-memory",
        reliability=SourceReliability.HIGH,
    )
    signal = Signal(
        signal_id="sig-agent-memory",
        signal_type=SignalType.AI_NEWS,
        board_type=BoardType.AI_NEWS,
        title="Agent Memory update",
        summary="OpenAI launches an agent memory product update.",
        content="OpenAI launches an agent memory product update with workflow support.",
        url="https://example.com/agent-memory",
        source=source,
        published_at=published,
        raw_payload={"raw_payload": "source-only"},
        content_hash="hash-agent-memory",
        canonical_key="agent-memory",
        confidence=Confidence(value=0.82, factors=[ScoreFactor(name="source_authority", value=0.9)]),
    )
    technology = Technology(
        technology_id="tech-agent-memory",
        name="Agent Memory",
        normalized_key="agent_memory",
        category=TechnologyCategory.AGENT,
        confidence=Confidence(value=0.86),
        first_seen_signal_id=signal.signal_id,
    )
    extraction = ExtractionResult(signal_id=signal.signal_id, technologies=[technology])
    technology_ref = ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name)
    relation = Relation(
        relation_id="rel-agent-memory-adopts",
        relation_type=RelationType.ADOPTS,
        source_ref=ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title),
        target_ref=technology_ref,
        direction=RelationDirection.DIRECTED,
        evidence_signal_ids=[signal.signal_id],
        confidence=Confidence(value=0.8),
    )
    trend = Trend(
        target_ref=technology_ref,
        time_window=TimeWindow(start_at=published, end_at=published, label="test"),
        score=Score(value=0.82, factors=[ScoreFactor(name="trend_score", value=0.82)]),
        direction=TrendDirection.RISING,
        signal_count=1,
        previous_signal_count=0,
        explanation="Agent Memory is rising.",
    )
    quality = Quality(
        target_ref=ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title),
        score=Score(value=0.88, factors=[ScoreFactor(name="source_reliability", value=0.88)]),
        explanation="High quality source.",
    )
    maturity = Maturity(
        technology_ref=technology_ref,
        stage=MaturityStage.EARLY_ADOPTION,
        score=Score(value=0.7),
        evidence_summary="Product adoption signal.",
        supporting_relations=[relation.relation_id],
    )
    impact = Impact(
        target_ref=technology_ref,
        score=Score(value=0.78, factors=[ScoreFactor(name="impact_score", value=0.78)]),
        impact_areas=[ImpactArea.PRODUCT],
        explanation="Product impact.",
    )
    radar_item = TechnologyRadarItem(
        technology_ref=technology_ref,
        name=technology.name,
        category=technology.category,
        trend_direction=TrendDirection.RISING,
        trend_score=trend.score,
        maturity_stage=maturity.stage,
        maturity_score=maturity.score,
        impact_score=impact.score,
        quality_score=quality.score,
        paper_count=0,
        project_count=0,
        community_discussion_count=0,
        news_count=1,
        key_relations=[relation.relation_id],
        summary="Agent Memory radar summary.",
        recommendation=RadarRecommendation.INVESTIGATE,
    )
    analysis = AnalysisResult(
        trends=[trend],
        qualities=[quality],
        maturities=[maturity],
        impacts=[impact],
        radar_items=[radar_item],
    )
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    return signal, extraction, [relation], analysis, context


class _FakeReportContextProvider:
    def __init__(self) -> None:
        self.requests = []

    def build_context(self, request):
        self.requests.append(request)
        return ReportMemoryContextResult(
            topic=request.topic,
            context=IntelligenceMemoryContext(
                query=request.topic,
                topic=request.topic,
                claims=[
                    ClaimMemory(
                        claim_id="claim-1",
                        run_id="older-run",
                        text="Known historical claim",
                    )
                ],
                metadata={"memory_available": True},
            ),
            prompt_context="Known claims:\n- Known historical claim",
        )


class _FailingReportContextProvider:
    def build_context(self, request):
        raise RuntimeError("memory backend unavailable")
