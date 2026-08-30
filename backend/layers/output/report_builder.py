from __future__ import annotations

from typing import Any

from backend.foundation import (
    BoardCard,
    BoardType,
    DetailPage,
    DetailSectionType,
    Insight,
    Report,
    ReportSection,
    ReportType,
    build_stable_id,
)
from backend.layers.analysis.pipeline import TechnologyRadarItem


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
        retrieved_context: dict[str, Any] | None = None,
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
        if retrieved_context is not None:
            prompt_context = str(retrieved_context.get("prompt_context") or "").strip()
            if prompt_context:
                sections.append(
                    ReportSection(
                        title="Retrieved Context",
                        section_type=DetailSectionType.EVIDENCE,
                        content=prompt_context,
                        metadata={
                            "source": "report_memory_context",
                            "topic": retrieved_context.get("topic"),
                        },
                    )
                )
        metadata = {"board_type": board_type.value}
        if retrieved_context is not None:
            metadata["rag_context"] = dict(retrieved_context)
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
            metadata=metadata,
        )


__all__ = ["ReportBuilder"]
