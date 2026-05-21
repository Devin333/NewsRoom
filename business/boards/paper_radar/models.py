from __future__ import annotations

from datetime import datetime

from pydantic import Field

from business.foundation import BoardCard, Claim, Maturity, ObjectRef, PrimitiveModel


class PaperRadarItem(PrimitiveModel):
    card: BoardCard
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    abstract: str = ""
    technologies: list[ObjectRef] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    has_code: bool = False
    code_refs: list[ObjectRef] = Field(default_factory=list)
    related_projects: list[ObjectRef] = Field(default_factory=list)
    related_discussions: list[ObjectRef] = Field(default_factory=list)
    maturity_hint: Maturity | None = None
