from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation import PrimitiveModel
from backend.research.domain.common import SourceLineage, require_text, unique_texts


class ResearchSection(PrimitiveModel):
    section_id: str
    title: str
    level: int = 1
    text: str = ""
    page_start: int | None = None
    page_end: int | None = None
    source_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("section_id", "title", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "section fields")

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ResearchSection":
        if self.level < 1:
            raise ValueError("section level must be greater than zero")
        if self.page_start is not None and self.page_start < 0:
            raise ValueError("page_start must be non-negative")
        if self.page_end is not None and self.page_start is not None and self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ResearchFigure(PrimitiveModel):
    figure_id: str
    caption: str
    source_ref: str
    image_ref: str | None = None
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("figure_id", "caption", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "figure fields")


class ResearchTable(PrimitiveModel):
    table_id: str
    caption: str
    source_ref: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("table_id", "caption", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "table fields")

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, value: list[str]) -> list[str]:
        return unique_texts(value)


class ResearchEquation(PrimitiveModel):
    equation_id: str
    latex: str
    source_ref: str
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("equation_id", "latex", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "equation fields")


class ResearchReference(PrimitiveModel):
    reference_id: str
    title: str
    source_ref: str
    authors: list[str] = Field(default_factory=list)
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reference_id", "title", "source_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reference fields")

    @field_validator("authors")
    @classmethod
    def _unique_authors(cls, value: list[str]) -> list[str]:
        return unique_texts(value)


class ResearchDocument(PrimitiveModel):
    paper_id: str
    source_hash: str
    sections: list[ResearchSection] = Field(default_factory=list)
    figures: list[ResearchFigure] = Field(default_factory=list)
    tables: list[ResearchTable] = Field(default_factory=list)
    equations: list[ResearchEquation] = Field(default_factory=list)
    references: list[ResearchReference] = Field(default_factory=list)
    lineage: SourceLineage
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "source_hash")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "document fields")

    @model_validator(mode="after")
    def _require_lineage(self) -> "ResearchDocument":
        self.lineage.require_refs("research document requires source lineage")
        return self


__all__ = [
    "ResearchDocument",
    "ResearchEquation",
    "ResearchFigure",
    "ResearchReference",
    "ResearchSection",
    "ResearchTable",
]
