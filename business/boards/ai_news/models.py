from __future__ import annotations

from pydantic import Field

from business.foundation import BoardCard, Impact, ObjectRef, PrimitiveModel


class AINewsBoardItem(PrimitiveModel):
    card: BoardCard
    news_type: str = "unknown"
    companies: list[ObjectRef] = Field(default_factory=list)
    products: list[ObjectRef] = Field(default_factory=list)
    technologies: list[ObjectRef] = Field(default_factory=list)
    impact: Impact | None = None
