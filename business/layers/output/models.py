from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from pydantic import Field

from business.foundation import (
    BoardCard,
    BoardType,
    DetailPage,
    DetailSectionType,
    DisplayMetric,
    Insight,
    Relation,
)
from business.foundation.primitives import PrimitiveModel
from business.layers.analysis.pipeline import TechnologyRadarItem


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


__all__ = ["BoardOutput", "BoardOutputSection", "BoardOutputStats"]
