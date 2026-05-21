from __future__ import annotations

from business.layers.analysis import pipeline as rules
from business.layers.analysis.pipeline import TechnologyRadarItem


class TechnologyRadarAnalyzer:
    def analyze(self, signals, extraction_results, relations, context=None, *, trends=None, qualities=None, maturities=None, impacts=None):
        trends = trends or []
        qualities = qualities or []
        maturities = maturities or []
        impacts = impacts or []
        trend_map = {trend.target_ref.object_id: trend for trend in trends}
        quality_map = {quality.target_ref.object_id: quality for quality in qualities}
        maturity_map = {maturity.technology_ref.object_id: maturity for maturity in maturities}
        impact_map = {impact.target_ref.object_id: impact for impact in impacts}
        items = []
        seen: set[str] = set()
        for result in extraction_results:
            for technology in result.technologies:
                if technology.technology_id in seen:
                    continue
                seen.add(technology.technology_id)
                trend = trend_map.get(technology.technology_id)
                maturity = maturity_map.get(technology.technology_id)
                impact = impact_map.get(technology.technology_id)
                quality = quality_map.get(technology.technology_id)
                related_relations = [relation for relation in relations if relation.target_ref.object_id == technology.technology_id]
                paper_count = len([relation for relation in related_relations if relation.relation_type.value == "proposes"])
                project_count = len([relation for relation in related_relations if relation.relation_type.value == "implements"])
                community_count = len([relation for relation in related_relations if relation.relation_type.value == "discusses"])
                news_count = len([relation for relation in related_relations if relation.relation_type.value == "adopts"])
                recommendation = rules._recommendation(trend, maturity, impact)
                items.append(
                    TechnologyRadarItem(
                        technology_ref=rules.ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        name=technology.name,
                        category=technology.category,
                        trend_direction=trend.direction if trend else rules.TrendDirection.UNKNOWN,
                        trend_score=trend.score if trend else rules.Score(value=0.0, factors=[]),
                        maturity_stage=maturity.stage if maturity else rules.MaturityStage.UNKNOWN,
                        maturity_score=maturity.score if maturity else rules.Score(value=0.0, factors=[]),
                        impact_score=impact.score if impact else rules.Score(value=0.0, factors=[]),
                        quality_score=quality.score if quality else rules.Score(value=0.5, factors=[]),
                        paper_count=paper_count,
                        project_count=project_count,
                        community_discussion_count=community_count,
                        news_count=news_count,
                        key_relations=[relation.relation_id for relation in related_relations],
                        summary=f"{technology.name} radar summary from {len(related_relations)} relation(s).",
                        recommendation=recommendation,
                    )
                )
        return items


__all__ = ["TechnologyRadarAnalyzer", "TechnologyRadarItem"]
