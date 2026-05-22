from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import Field

from business.foundation import (
    Impact,
    ImpactArea,
    Maturity,
    MaturityStage,
    ObjectRef,
    Quality,
    RadarRecommendation,
    Relation,
    Signal,
    Score,
    Technology,
    TechnologyCategory,
    TimeWindow,
    Trend,
    TrendDirection,
)
from business.foundation.primitives import PrimitiveModel
from business.layers.extraction.models import ExtractionResult


class AnalysisWarning(PrimitiveModel):
    target_ref: ObjectRef | None = None
    warning_type: str
    message: str


class TechnologyRadarItem(PrimitiveModel):
    technology_ref: ObjectRef
    name: str
    category: TechnologyCategory
    trend_direction: TrendDirection
    trend_score: Score
    maturity_stage: MaturityStage
    maturity_score: Score
    impact_score: Score
    quality_score: Score
    paper_count: int
    project_count: int
    community_discussion_count: int
    news_count: int
    key_relations: list[str] = Field(default_factory=list)
    summary: str
    recommendation: RadarRecommendation


class AnalysisResult(PrimitiveModel):
    trends: list[Trend] = Field(default_factory=list)
    qualities: list[Quality] = Field(default_factory=list)
    maturities: list[Maturity] = Field(default_factory=list)
    impacts: list[Impact] = Field(default_factory=list)
    radar_items: list[TechnologyRadarItem] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisPipeline:
    def __init__(
        self,
        *,
        trend_analyzer: Any | None = None,
        quality_analyzer: Any | None = None,
        maturity_analyzer: Any | None = None,
        impact_analyzer: Any | None = None,
        radar_analyzer: Any | None = None,
    ) -> None:
        from business.layers.analysis.impact_analyzer import ImpactAnalyzer
        from business.layers.analysis.maturity_analyzer import MaturityAnalyzer
        from business.layers.analysis.quality_analyzer import QualityAnalyzer
        from business.layers.analysis.technology_radar import TechnologyRadarAnalyzer
        from business.layers.analysis.trend_analyzer import TrendAnalyzer

        self.trend_analyzer = trend_analyzer or TrendAnalyzer()
        self.quality_analyzer = quality_analyzer or QualityAnalyzer()
        self.maturity_analyzer = maturity_analyzer or MaturityAnalyzer()
        self.impact_analyzer = impact_analyzer or ImpactAnalyzer()
        self.radar_analyzer = radar_analyzer or TechnologyRadarAnalyzer()

    def run(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        context: Any,
    ) -> AnalysisResult:
        trends = self.trend_analyzer.analyze(signals, extraction_results, relations, context)
        qualities = self.quality_analyzer.analyze(signals, extraction_results, relations, context)
        maturities = self.maturity_analyzer.analyze(signals, extraction_results, relations, context)
        impacts = self.impact_analyzer.analyze(signals, extraction_results, relations, context, trends=trends, qualities=qualities)
        radar_items = self.radar_analyzer.analyze(
            signals,
            extraction_results,
            relations,
            context,
            trends=trends,
            qualities=qualities,
            maturities=maturities,
            impacts=impacts,
        )
        return AnalysisResult(
            trends=trends,
            qualities=qualities,
            maturities=maturities,
            impacts=impacts,
            radar_items=radar_items,
            warnings=[],
            metadata={
                "board_types": sorted({signal.board_type.value for signal in signals}),
                "technology_count": len({technology.normalized_key for result in extraction_results for technology in result.technologies}),
            },
        )

    def _build_trends(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        context: Any,
    ) -> list[Trend]:
        return self.trend_analyzer.analyze(signals, extraction_results, relations, context)

    def _legacy_build_trends(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        context: Any,
    ) -> list[Trend]:
        windows = _time_window(context)
        signal_groups = _signals_by_technology(signals, extraction_results, relations)
        trends: list[Trend] = []
        for technology_key, payload in signal_groups.items():
            signal_count = len(payload["signals"])
            previous_count = max(0, signal_count - 1)
            growth_rate = None if previous_count == 0 else (signal_count - previous_count) / previous_count
            direction = _trend_direction(signal_count, previous_count, growth_rate)
            trend_score = _trend_score(signal_count, previous_count, growth_rate, len(payload["boards"]))
            trends.append(
                Trend(
                    target_ref=payload["ref"],
                    time_window=windows,
                    score=Score(value=trend_score, factors=_trend_factors(signal_count, previous_count, growth_rate, len(payload["boards"]))),
                    direction=direction,
                    signal_count=signal_count,
                    previous_signal_count=previous_count,
                    growth_rate=growth_rate,
                    explanation=f"{payload['name']} appears in {signal_count} signal(s) across {len(payload['boards'])} board(s).",
                )
            )
        return trends

    def _build_qualities(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
    ) -> list[Quality]:
        return self.quality_analyzer.analyze(signals, extraction_results, relations)

    def _legacy_build_qualities(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
    ) -> list[Quality]:
        qualities: list[Quality] = []
        for signal in signals:
            score_value, factors = _signal_quality(signal, extraction_results, relations)
            qualities.append(
                Quality(
                    target_ref=ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title),
                    score=Score(value=score_value, factors=factors),
                    dimensions={
                        "source_reliability": Score(value=_factor_value(factors, "source_reliability"), factors=[]),
                        "freshness": Score(value=_factor_value(factors, "freshness"), factors=[]),
                        "relevance": Score(value=_factor_value(factors, "relevance"), factors=[]),
                        "impact": Score(value=_factor_value(factors, "impact"), factors=[]),
                        "specificity": Score(value=_factor_value(factors, "specificity"), factors=[]),
                    },
                    explanation=f"Quality for {signal.title}",
                )
            )
        for result in extraction_results:
            for technology in result.technologies:
                quality_score = _technology_quality(technology, relations)
                qualities.append(
                    Quality(
                        target_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        score=Score(value=quality_score, factors=_quality_factors_for_technology(technology, relations)),
                        dimensions={},
                        explanation=f"Quality for {technology.name}",
                    )
                )
        return qualities

    def _build_maturities(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
    ) -> list[Maturity]:
        return self.maturity_analyzer.analyze(signals, extraction_results, relations)

    def _legacy_build_maturities(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
    ) -> list[Maturity]:
        maturities: list[Maturity] = []
        for result in extraction_results:
            for technology in result.technologies:
                paper_relations = [relation for relation in relations if relation.relation_type.value == "proposes" and relation.target_ref.object_id == technology.technology_id]
                project_relations = [relation for relation in relations if relation.relation_type.value == "implements" and relation.target_ref.object_id == technology.technology_id]
                community_relations = [relation for relation in relations if relation.relation_type.value == "discusses" and relation.target_ref.object_id == technology.technology_id]
                news_relations = [relation for relation in relations if relation.relation_type.value == "adopts" and relation.target_ref.object_id == technology.technology_id]
                score_value = _maturity_score(len(paper_relations), len(project_relations), len(community_relations), len(news_relations), technology)
                stage = _maturity_stage(score_value, len(paper_relations), len(project_relations), len(news_relations))
                maturities.append(
                    Maturity(
                        technology_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        stage=stage,
                        score=Score(
                            value=score_value,
                            factors=[
                                _score_factor("paper_signal", min(1.0, len(paper_relations) / 3.0)),
                                _score_factor("project_implementation_signal", min(1.0, len(project_relations) / 3.0)),
                                _score_factor("community_usage_signal", min(1.0, len(community_relations) / 3.0)),
                                _score_factor("product_adoption_signal", min(1.0, len(news_relations) / 2.0)),
                                _score_factor("quality_signal", technology.confidence.value),
                            ],
                        ),
                        evidence_summary=f"{technology.name} has {len(paper_relations)} paper relation(s), {len(project_relations)} project relation(s).",
                        supporting_relations=[relation.relation_id for relation in paper_relations + project_relations + community_relations + news_relations],
                    )
                )
        return maturities

    def _build_impacts(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        trends: list[Trend],
        qualities: list[Quality],
    ) -> list[Impact]:
        return self.impact_analyzer.analyze(signals, extraction_results, relations, trends=trends, qualities=qualities)

    def _legacy_build_impacts(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        trends: list[Trend],
        qualities: list[Quality],
    ) -> list[Impact]:
        impacts: list[Impact] = []
        trend_map = {trend.target_ref.object_id: trend for trend in trends}
        quality_map = {quality.target_ref.object_id: quality for quality in qualities}
        for result in extraction_results:
            for technology in result.technologies:
                related_relations = [relation for relation in relations if relation.target_ref.object_id == technology.technology_id]
                areas = _impact_areas_for_relations(related_relations)
                score_value = _impact_score(related_relations, trend_map, quality_map, technology.technology_id)
                trend = trend_map.get(technology.technology_id)
                quality = quality_map.get(technology.technology_id)
                impacts.append(
                    Impact(
                        target_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        score=Score(
                            value=score_value,
                            factors=[
                                _score_factor("source_authority", min(1.0, len({signal.source.source_id for signal in signals if signal.signal_id in {relation.source_ref.object_id for relation in related_relations}}) / 4.0)),
                                _score_factor("cross_board_presence", min(1.0, len({signal.board_type.value for signal in signals if signal.signal_id in {relation.source_ref.object_id for relation in related_relations}}) / 4.0)),
                                _score_factor("relation_centrality", min(1.0, len(related_relations) / 5.0)),
                                _score_factor("trend_score", trend.score.value if trend else 0.0),
                                _score_factor("quality_score", quality.score.value if quality else 0.5),
                                _score_factor("affected_area_count", min(1.0, len(areas) / 4.0)),
                            ],
                        ),
                        impact_areas=areas,
                        explanation=f"{technology.name} appears across {len(related_relations)} relation(s).",
                    )
                )
        return impacts

    def _build_radar_items(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        trends: list[Trend],
        qualities: list[Quality],
        maturities: list[Maturity],
        impacts: list[Impact],
    ) -> list[TechnologyRadarItem]:
        return self.radar_analyzer.analyze(
            signals,
            extraction_results,
            relations,
            trends=trends,
            qualities=qualities,
            maturities=maturities,
            impacts=impacts,
        )

    def _legacy_build_radar_items(
        self,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        trends: list[Trend],
        qualities: list[Quality],
        maturities: list[Maturity],
        impacts: list[Impact],
    ) -> list[TechnologyRadarItem]:
        trend_map = {trend.target_ref.object_id: trend for trend in trends}
        quality_map = {quality.target_ref.object_id: quality for quality in qualities}
        maturity_map = {maturity.technology_ref.object_id: maturity for maturity in maturities}
        impact_map = {impact.target_ref.object_id: impact for impact in impacts}
        items: list[TechnologyRadarItem] = []
        for result in extraction_results:
            for technology in result.technologies:
                trend = trend_map.get(technology.technology_id)
                maturity = maturity_map.get(technology.technology_id)
                impact = impact_map.get(technology.technology_id)
                quality = quality_map.get(technology.technology_id)
                related_relations = [relation for relation in relations if relation.target_ref.object_id == technology.technology_id]
                paper_count = len([relation for relation in related_relations if relation.relation_type.value == "proposes"])
                project_count = len([relation for relation in related_relations if relation.relation_type.value == "implements"])
                community_count = len([relation for relation in related_relations if relation.relation_type.value == "discusses"])
                news_count = len([relation for relation in related_relations if relation.relation_type.value == "adopts"])
                recommendation = _recommendation(trend, maturity, impact)
                items.append(
                    TechnologyRadarItem(
                        technology_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        name=technology.name,
                        category=technology.category,
                        trend_direction=trend.direction if trend else TrendDirection.UNKNOWN,
                        trend_score=trend.score if trend else Score(value=0.0, factors=[]),
                        maturity_stage=maturity.stage if maturity else MaturityStage.UNKNOWN,
                        maturity_score=maturity.score if maturity else Score(value=0.0, factors=[]),
                        impact_score=impact.score if impact else Score(value=0.0, factors=[]),
                        quality_score=quality.score if quality else Score(value=0.5, factors=[]),
                        paper_count=paper_count,
                        project_count=project_count,
                        community_discussion_count=community_count,
                        news_count=news_count,
                        key_relations=[relation.relation_id for relation in related_relations],
                        summary=f"{technology.name} radar summary",
                        recommendation=recommendation,
                    )
                )
        return items


def _time_window(context: Any) -> TimeWindow:
    reference = getattr(context, "reference_time", None) or datetime.now(UTC)
    end = reference.astimezone(UTC) if reference.tzinfo else reference.replace(tzinfo=UTC)
    start = end - timedelta(days=7)
    return TimeWindow(start_at=start, end_at=end, label="last_7_days")


def _signals_by_technology(
    signals: list[Signal],
    extraction_results: list[ExtractionResult],
    relations: list[Relation],
) -> dict[str, dict[str, Any]]:
    lookup = {result.signal_id: result for result in extraction_results}
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"signals": [], "boards": set(), "ref": None, "name": ""})
    for signal in signals:
        extraction = lookup.get(signal.signal_id)
        if extraction is None:
            continue
        for technology in extraction.technologies:
            payload = grouped[technology.technology_id]
            payload["signals"].append(signal)
            payload["boards"].add(signal.board_type.value)
            payload["ref"] = ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name)
            payload["name"] = technology.name
    return grouped


def _trend_direction(signal_count: int, previous_count: int, growth_rate: float | None) -> TrendDirection:
    if signal_count == 0:
        return TrendDirection.UNKNOWN
    if growth_rate is None:
        return TrendDirection.UNKNOWN
    if growth_rate >= 1.0 and signal_count >= 3:
        return TrendDirection.SPIKE
    if growth_rate >= 0.3:
        return TrendDirection.RISING
    if -0.2 < growth_rate < 0.3:
        return TrendDirection.STABLE
    if growth_rate <= -0.2:
        return TrendDirection.FALLING
    return TrendDirection.UNKNOWN


def _trend_score(signal_count: int, previous_count: int, growth_rate: float | None, board_count: int) -> float:
    normalized_growth = 0.0 if growth_rate is None else max(0.0, min(1.0, (growth_rate + 1.0) / 2.0))
    current = min(1.0, signal_count / 5.0)
    diversity = min(1.0, board_count / 4.0)
    freshness = 0.8 if signal_count else 0.1
    score = 0.25 * normalized_growth + 0.20 * current + 0.20 * diversity + 0.20 * diversity + 0.15 * freshness
    return round(min(1.0, score), 4)


def _trend_factors(signal_count: int, previous_count: int, growth_rate: float | None, board_count: int) -> list[Any]:
    return [
        _score_factor("current_signal_count", min(1.0, signal_count / 5.0)),
        _score_factor("previous_signal_count", min(1.0, previous_count / 5.0)),
        _score_factor("growth_rate", 0.0 if growth_rate is None else max(0.0, min(1.0, (growth_rate + 1.0) / 2.0))),
        _score_factor("cross_board_presence", min(1.0, board_count / 4.0)),
    ]


def _signal_quality(signal: Signal, extraction_results: list[ExtractionResult], relations: list[Relation]) -> tuple[float, list[Any]]:
    source_reliability = _source_reliability(signal)
    freshness = _freshness_score(signal)
    relevance = _relevance_score(signal, extraction_results)
    impact = _signal_impact_score(signal, relations)
    specificity = _specificity_score(signal)
    score = round(0.30 * source_reliability + 0.20 * freshness + 0.20 * relevance + 0.20 * impact + 0.10 * specificity, 4)
    return score, [
        _score_factor("source_reliability", source_reliability),
        _score_factor("freshness", freshness),
        _score_factor("relevance", relevance),
        _score_factor("impact", impact),
        _score_factor("specificity", specificity),
    ]


def _technology_quality(technology: Technology, relations: list[Relation]) -> float:
    relation_count = len([relation for relation in relations if relation.target_ref.object_id == technology.technology_id])
    return round(min(1.0, 0.4 + 0.1 * relation_count + 0.3 * technology.confidence.value), 4)


def _quality_factors_for_technology(technology: Technology, relations: list[Relation]) -> list[Any]:
    relation_count = len([relation for relation in relations if relation.target_ref.object_id == technology.technology_id])
    return [
        _score_factor("activity", min(1.0, relation_count / 4.0)),
        _score_factor("documentation", 0.6),
        _score_factor("community_adoption", min(1.0, relation_count / 3.0)),
        _score_factor("maintainability", 0.6),
        _score_factor("technical_relevance", technology.confidence.value),
        _score_factor("novelty", 0.7),
    ]


def _maturity_score(paper_count: int, project_count: int, community_count: int, news_count: int, technology: Technology) -> float:
    score = (
        0.20 * min(1.0, paper_count / 3.0)
        + 0.25 * min(1.0, project_count / 3.0)
        + 0.20 * min(1.0, community_count / 3.0)
        + 0.25 * min(1.0, news_count / 2.0)
        + 0.10 * technology.confidence.value
    )
    return round(min(1.0, score), 4)


def _maturity_stage(score: float, paper_count: int, project_count: int, news_count: int) -> MaturityStage:
    if paper_count == 0 and project_count == 0:
        return MaturityStage.UNKNOWN
    if score < 0.20:
        return MaturityStage.RESEARCH
    if score < 0.40:
        return MaturityStage.PROTOTYPE
    if score < 0.65:
        return MaturityStage.EARLY_ADOPTION
    if score < 0.85:
        return MaturityStage.PRODUCTIONIZING
    return MaturityStage.MAINSTREAM


def _impact_score(relations: list[Relation], trend_map: dict[str, Trend], quality_map: dict[str, Quality], technology_id: str) -> float:
    source_authority = min(1.0, len(relations) / 4.0)
    cross_board_presence = min(1.0, len({relation.source_ref.object_type for relation in relations}) / 4.0)
    relation_centrality = min(1.0, len(relations) / 5.0)
    trend = trend_map.get(technology_id)
    quality = quality_map.get(technology_id)
    trend_score = trend.score.value if trend else 0.0
    quality_score = quality.score.value if quality else 0.5
    areas = _impact_areas_for_relations(relations)
    affected_area_count = min(1.0, len(areas) / 4.0)
    return round(
        0.20 * source_authority
        + 0.20 * cross_board_presence
        + 0.20 * relation_centrality
        + 0.15 * trend_score
        + 0.15 * quality_score
        + 0.10 * affected_area_count,
        4,
    )


def _impact_areas_for_relations(relations: list[Relation]) -> list[ImpactArea]:
    if not relations:
        return [ImpactArea.RESEARCH]
    areas = {ImpactArea.ENGINEERING, ImpactArea.COMMUNITY}
    if any(relation.relation_type.value == "adopts" for relation in relations):
        areas.add(ImpactArea.BUSINESS)
        areas.add(ImpactArea.PRODUCT)
    if any(relation.relation_type.value == "proposes" for relation in relations):
        areas.add(ImpactArea.RESEARCH)
    return sorted(areas, key=lambda item: item.value)


def _recommendation(trend: Trend | None, maturity: Maturity | None, impact: Impact | None) -> RadarRecommendation:
    if trend is None or maturity is None or impact is None:
        return RadarRecommendation.WATCH
    if trend.score.value >= 0.75 and impact.score.value >= 0.75 and maturity.stage in {MaturityStage.EARLY_ADOPTION, MaturityStage.PRODUCTIONIZING, MaturityStage.MAINSTREAM}:
        return RadarRecommendation.HIGH_PRIORITY
    if trend.score.value >= 0.7 and maturity.stage in {MaturityStage.RESEARCH, MaturityStage.PROTOTYPE}:
        return RadarRecommendation.INVESTIGATE
    if maturity.stage in {MaturityStage.PRODUCTIONIZING, MaturityStage.MAINSTREAM} and impact.score.value >= 0.55:
        return RadarRecommendation.ADOPT_CAREFULLY
    if trend.score.value < 0.35 and impact.score.value < 0.4:
        return RadarRecommendation.IGNORE_FOR_NOW
    return RadarRecommendation.WATCH


def _source_reliability(signal: Signal) -> float:
    mapping = {
        "ai_news": 0.85,
        "github_project": 0.75,
        "paper": 0.9,
        "community_discussion": 0.6,
    }
    return mapping.get(signal.signal_type.value, 0.6)


def _freshness_score(signal: Signal) -> float:
    if signal.published_at is None:
        return 0.5
    age_days = max(0.0, (datetime.now(UTC) - signal.published_at.astimezone(UTC)).days if signal.published_at.tzinfo else (datetime.now(UTC) - signal.published_at.replace(tzinfo=UTC)).days)
    return max(0.0, min(1.0, 1.0 - age_days / 14.0))


def _relevance_score(signal: Signal, extraction_results: list[ExtractionResult]) -> float:
    extraction = next((result for result in extraction_results if result.signal_id == signal.signal_id), None)
    if extraction is None:
        return 0.4
    count = len(extraction.technologies) + len(extraction.entities) + len(extraction.topics)
    return min(1.0, 0.4 + count * 0.15)


def _signal_impact_score(signal: Signal, relations: list[Relation]) -> float:
    relation_count = len([relation for relation in relations if relation.source_ref.object_id == signal.signal_id or relation.target_ref.object_id == signal.signal_id])
    return min(1.0, relation_count / 5.0)


def _specificity_score(signal: Signal) -> float:
    text = " ".join([signal.title, signal.summary or "", signal.content or ""]).strip()
    if len(text) > 500:
        return 0.8
    if len(text) > 120:
        return 0.65
    return 0.5


def _score_factor(name: str, value: float) -> Any:
    return {
        "name": name,
        "value": round(max(0.0, min(1.0, value)), 4),
        "weight": 1.0,
    }


def _factor_value(factors: list[Any], name: str) -> float:
    for factor in factors:
        if isinstance(factor, dict) and factor.get("name") == name:
            try:
                return float(factor.get("value", 0.0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0
