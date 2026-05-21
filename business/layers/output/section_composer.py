from __future__ import annotations

from business.foundation import BoardCard, DetailSection, DetailSectionType, Report
from business.layers.output.models import BoardOutputSection


class SectionComposer:
    def top_cards(self, cards: list[BoardCard]) -> DetailSection:
        return DetailSection(title="Top Cards", section_type=DetailSectionType.KEY_POINTS, cards=cards)

    def from_report(self, report: Report) -> list[BoardOutputSection]:
        return [
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


__all__ = ["SectionComposer"]
