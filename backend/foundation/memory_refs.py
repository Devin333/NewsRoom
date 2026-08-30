from __future__ import annotations

from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.primitives import PrimitiveModel, SourceRef, build_stable_id, ensure_utc


class BusinessMemoryRef(PrimitiveModel):
    memory_id: str
    memory_type: str = "retrieval"
    query: str | None = None
    source_ref: SourceRef | None = None
    score: float | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("memory_id", "memory_type")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("memory ref text fields must be non-empty")
        return text

    @field_validator("score")
    @classmethod
    def _optional_unit_interval(cls, value: float | None) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("memory ref score must be between 0 and 1")
        return round(numeric, 4)

    @model_validator(mode="after")
    def _normalize_retrieved_at(self) -> "BusinessMemoryRef":
        object.__setattr__(self, "retrieved_at", ensure_utc(self.retrieved_at) or self.retrieved_at)
        return self

    @classmethod
    def create(
        cls,
        *,
        memory_type: str = "retrieval",
        query: str | None = None,
        source_ref: SourceRef | None = None,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "BusinessMemoryRef":
        return cls(
            memory_id=build_stable_id("memory", memory_type, query or "", source_ref.source_id if source_ref else ""),
            memory_type=memory_type,
            query=query,
            source_ref=source_ref,
            score=score,
            metadata=metadata or {},
        )


__all__ = ["BusinessMemoryRef"]
