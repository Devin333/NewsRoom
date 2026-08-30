from __future__ import annotations

from pydantic import Field, field_validator

from backend.foundation.primitives import Confidence, PrimitiveModel
from backend.foundation.taxonomy import TechnologyCategory


class Technology(PrimitiveModel):
    technology_id: str
    name: str
    normalized_key: str
    category: TechnologyCategory
    subcategory: str | None = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None
    first_seen_signal_id: str | None = None
    confidence: Confidence
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("technology_id", "name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("technology fields must be non-empty")
        return text


__all__ = ["Technology"]
