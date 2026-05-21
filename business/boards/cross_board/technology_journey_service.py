from __future__ import annotations

from business.boards.cross_board.models import TechnologyJourney, TechnologyJourneyStage
from business.foundation import ObjectRef, Relation
from business.layers.analysis import AnalysisResult


class TechnologyJourneyService:
    def build_journey(
        self,
        technology_ref: ObjectRef,
        relations: list[Relation],
        analysis: AnalysisResult | None = None,
    ) -> TechnologyJourney:
        related = [relation for relation in relations if relation.target_ref.object_id == technology_ref.object_id]
        stages: list[TechnologyJourneyStage] = []
        for relation_type, stage_type, title in (
            ("proposes", "research_origin", "Research Origin"),
            ("implements", "project_implementation", "Project Implementation"),
            ("discusses", "community_discussion", "Community Discussion"),
            ("adopts", "product_adoption", "Product Adoption"),
        ):
            stage_relations = [relation for relation in related if relation.relation_type.value == relation_type]
            if not stage_relations:
                continue
            stages.append(
                TechnologyJourneyStage(
                    stage_type=stage_type,
                    title=title,
                    object_refs=[relation.source_ref for relation in stage_relations],
                    evidence_relation_ids=[relation.relation_id for relation in stage_relations],
                    summary=f"{len(stage_relations)} {relation_type} relation(s).",
                )
            )
        maturity = next((item for item in (analysis.maturities if analysis else []) if item.technology_ref.object_id == technology_ref.object_id), None)
        trend = next((item for item in (analysis.trends if analysis else []) if item.target_ref.object_id == technology_ref.object_id), None)
        impact = next((item for item in (analysis.impacts if analysis else []) if item.target_ref.object_id == technology_ref.object_id), None)
        return TechnologyJourney(
            technology_ref=technology_ref,
            technology_name=technology_ref.label or technology_ref.object_id,
            stages=stages,
            maturity=maturity,
            trend=trend,
            impact=impact,
            summary=f"{technology_ref.label or technology_ref.object_id} has {len(stages)} journey stage(s).",
        )
