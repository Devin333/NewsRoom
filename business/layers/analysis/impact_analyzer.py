from __future__ import annotations

from business.layers.analysis import pipeline as rules


class ImpactAnalyzer:
    def analyze(self, signals, extraction_results, relations, context=None, *, trends=None, qualities=None):
        trends = trends or []
        qualities = qualities or []
        impacts = []
        trend_map = {trend.target_ref.object_id: trend for trend in trends}
        quality_map = {quality.target_ref.object_id: quality for quality in qualities}
        for result in extraction_results:
            for technology in result.technologies:
                related_relations = [relation for relation in relations if relation.target_ref.object_id == technology.technology_id]
                areas = rules._impact_areas_for_relations(related_relations)
                score_value = rules._impact_score(related_relations, trend_map, quality_map, technology.technology_id)
                trend = trend_map.get(technology.technology_id)
                quality = quality_map.get(technology.technology_id)
                impacts.append(
                    rules.Impact(
                        target_ref=rules.ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        score=rules.Score(
                            value=score_value,
                            factors=[
                                rules._score_factor("source_authority", min(1.0, len({signal.source.source_id for signal in signals if signal.signal_id in {relation.source_ref.object_id for relation in related_relations}}) / 4.0)),
                                rules._score_factor("cross_board_presence", min(1.0, len({signal.board_type.value for signal in signals if signal.signal_id in {relation.source_ref.object_id for relation in related_relations}}) / 4.0)),
                                rules._score_factor("relation_centrality", min(1.0, len(related_relations) / 5.0)),
                                rules._score_factor("trend_score", trend.score.value if trend else 0.0),
                                rules._score_factor("quality_score", quality.score.value if quality else 0.5),
                                rules._score_factor("affected_area_count", min(1.0, len(areas) / 4.0)),
                            ],
                        ),
                        impact_areas=areas,
                        explanation=f"{technology.name} appears across {len(related_relations)} relation(s).",
                    )
                )
        return impacts
