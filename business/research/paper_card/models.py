from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, canonicalize_url
from business.research.domain.analysis import ThreeMinuteRead
from business.research.domain.common import QualityFlag, ensure_utc, optional_text, require_text, unique_texts


class ResearchPaperCard(PrimitiveModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    published_at: datetime | None = None
    source_url: str
    pdf_url: str | None = None
    code_url: str | None = None
    github_repo: str | None = None
    github_stars: int | None = None
    github_star_growth_daily: float | None = None
    github_forks: int | None = None
    github_last_commit_at: datetime | None = None
    github_license: str | None = None
    three_minute_read: ThreeMinuteRead | None = None
    domains: list[str] = Field(default_factory=list)
    areas: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    reader_payload_status: Literal["missing", "pending", "ready", "needs_repair", "failed"] = "missing"
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "title", "source_url")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "paper card fields")

    @field_validator("github_stars", "github_forks")
    @classmethod
    def _non_negative_metric(cls, value: int | None) -> int | None:
        if value is None:
            return None
        numeric = int(value)
        if numeric < 0:
            raise ValueError("GitHub metrics must be non-negative")
        return numeric

    @model_validator(mode="after")
    def _normalize(self) -> "ResearchPaperCard":
        object.__setattr__(self, "authors", unique_texts(self.authors))
        for field_name in ("domains", "areas", "tasks", "methods", "benchmarks"):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        for field_name in ("source_url", "pdf_url", "code_url", "github_repo"):
            value = optional_text(getattr(self, field_name))
            object.__setattr__(self, field_name, canonicalize_url(value) if value else None)
        if self.source_url is None:
            raise ValueError("paper card requires source_url")
        if self.published_at is not None:
            object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        if self.github_last_commit_at is not None:
            object.__setattr__(self, "github_last_commit_at", ensure_utc(self.github_last_commit_at))
        return self


__all__ = ["ResearchPaperCard"]
