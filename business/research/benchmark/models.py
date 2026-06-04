from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel, normalize_key
from business.research.domain.common import require_text, unique_texts


class ResearchBenchmark(PrimitiveModel):
    benchmark_id: str
    name: str
    task: str
    dataset_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("benchmark_id", "name", "task")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "benchmark fields")

    @model_validator(mode="after")
    def _normalize_dataset_ids(self) -> "ResearchBenchmark":
        object.__setattr__(self, "benchmark_id", normalize_key(self.benchmark_id))
        object.__setattr__(self, "dataset_ids", unique_texts(self.dataset_ids))
        return self


class ResearchDataset(PrimitiveModel):
    dataset_id: str
    name: str
    version: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dataset_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "dataset fields")


class ResearchMetric(PrimitiveModel):
    metric_id: str
    name: str
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metric_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "metric fields")


class ResearchScore(PrimitiveModel):
    score_id: str
    paper_id: str
    benchmark_id: str
    dataset_id: str
    metric_id: str
    value: float
    baseline_id: str | None = None
    source_refs: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score_id", "paper_id", "benchmark_id", "dataset_id", "metric_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "score fields")

    @model_validator(mode="after")
    def _require_refs_and_range(self) -> "ResearchScore":
        refs = unique_texts(self.source_refs)
        if not refs:
            raise ValueError("benchmark score requires source refs")
        if not -1_000_000_000 <= float(self.value) <= 1_000_000_000:
            raise ValueError("benchmark score is outside supported range")
        object.__setattr__(self, "source_refs", refs)
        return self


class ResearchBaseline(PrimitiveModel):
    baseline_id: str
    name: str
    paper_id: str | None = None
    benchmark_id: str
    dataset_id: str
    metric_id: str
    value: float | None = None
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("baseline_id", "name", "benchmark_id", "dataset_id", "metric_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "baseline fields")


class ResearchSOTAClaim(PrimitiveModel):
    claim_id: str
    paper_id: str
    benchmark_id: str
    dataset_id: str
    metric_id: str
    score_id: str | None = None
    claim_text: str
    verification_status: Literal["candidate", "verified", "rejected", "conflicting"] = "candidate"
    source_refs: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim_id", "paper_id", "benchmark_id", "dataset_id", "metric_id", "claim_text")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "SOTA claim fields")

    @field_validator("source_refs")
    @classmethod
    def _require_source_refs(cls, value: list[str]) -> list[str]:
        refs = unique_texts(value)
        if not refs:
            raise ValueError("SOTA claim requires source refs")
        return refs


__all__ = [
    "ResearchBaseline",
    "ResearchBenchmark",
    "ResearchDataset",
    "ResearchMetric",
    "ResearchSOTAClaim",
    "ResearchScore",
]
