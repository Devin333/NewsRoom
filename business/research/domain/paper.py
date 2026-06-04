from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, canonicalize_url
from business.research.domain.common import ensure_utc, optional_text, require_text, unique_texts


class ResearchPaper(PrimitiveModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    published_at: datetime | None = None
    source: str = "unknown"
    source_url: str | None = None
    pdf_url: str | None = None
    code_url: str | None = None
    topics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "title")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "paper identity fields")

    @field_validator("abstract", "source")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchPaper":
        object.__setattr__(self, "authors", unique_texts(self.authors))
        object.__setattr__(self, "topics", unique_texts(self.topics))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        for field_name in ("source_url", "pdf_url", "code_url"):
            value = optional_text(getattr(self, field_name))
            object.__setattr__(self, field_name, canonicalize_url(value) if value else None)
        return self


class PaperSourceRecord(PrimitiveModel):
    source_id: str
    paper_id: str
    source_type: Literal["arxiv", "openreview", "publisher", "github", "manual", "other"] = "other"
    source_url: str
    fetched_at: datetime | None = None
    source_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id", "paper_id", "source_url")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "paper source fields")

    @model_validator(mode="after")
    def _normalize(self) -> "PaperSourceRecord":
        object.__setattr__(self, "source_url", canonicalize_url(self.source_url))
        if self.fetched_at is not None:
            object.__setattr__(self, "fetched_at", ensure_utc(self.fetched_at))
        return self


__all__ = ["PaperSourceRecord", "ResearchPaper"]
