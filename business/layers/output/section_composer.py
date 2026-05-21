from __future__ import annotations

from business.foundation import BoardCard, DetailSection, DetailSectionType


class SectionComposer:
    def top_cards(self, cards: list[BoardCard]) -> DetailSection:
        return DetailSection(title="Top Cards", section_type=DetailSectionType.KEY_POINTS, cards=cards)
