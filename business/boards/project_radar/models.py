from __future__ import annotations

from datetime import datetime

from pydantic import Field

from business.foundation import BoardCard, ObjectRef, PrimitiveModel, Quality


class ProjectRadarItem(PrimitiveModel):
    card: BoardCard
    repo_full_name: str
    stars: int = 0
    forks: int = 0
    language: str | None = None
    license: str | None = None
    last_pushed_at: datetime | None = None
    star_growth_7d: int | None = None
    quality: Quality | None = None
    implemented_technologies: list[ObjectRef] = Field(default_factory=list)
    related_papers: list[ObjectRef] = Field(default_factory=list)
    related_discussions: list[ObjectRef] = Field(default_factory=list)
