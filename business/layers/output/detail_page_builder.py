from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import (
    BoardCard,
    BoardType,
    DetailPage,
    DetailSection,
    DetailSectionType,
    Insight,
    ObjectRef,
    build_stable_id,
)
from business.foundation.primitives import PrimitiveModel
from business.layers.analysis.pipeline import AnalysisResult


class DetailBuildContext(PrimitiveModel):
    board_type: BoardType
    related_cards: list[BoardCard] = Field(default_factory=list)
    related_insights: list[Insight] = Field(default_factory=list)
    analysis: AnalysisResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DetailPageBuilder:
    def build_detail_page(
        self,
        primary_ref: ObjectRef,
        context: DetailBuildContext,
    ) -> DetailPage:
        return DetailPage(
            page_id=build_stable_id("page", context.board_type.value, primary_ref.object_id),
            board_type=context.board_type,
            title=primary_ref.label or primary_ref.object_id,
            summary=f"Details for {primary_ref.label or primary_ref.object_id}",
            primary_object_ref=primary_ref,
            sections=_sections(primary_ref, context.analysis),
            related_cards=list(context.related_cards),
            insights=list(context.related_insights),
            metadata=context.metadata,
        )


def _sections(primary_ref: ObjectRef, analysis: AnalysisResult | None) -> list[DetailSection]:
    sections = [
        DetailSection(
            title="Summary",
            section_type=DetailSectionType.SUMMARY,
            content=f"Detail page for {primary_ref.label or primary_ref.object_id}.",
        )
    ]
    if analysis is not None and analysis.radar_items:
        sections.append(
            DetailSection(
                title="Technology Radar",
                section_type=DetailSectionType.TECHNOLOGY_RADAR,
                content="Radar snapshot generated from analysis.",
            )
        )
    return sections


__all__ = ["DetailBuildContext", "DetailPageBuilder"]
