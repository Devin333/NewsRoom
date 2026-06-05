from __future__ import annotations

from pydantic import Field, field_validator

from business.foundation.primitives import Confidence, PrimitiveModel
from business.foundation.taxonomy import EntityType


class Entity(PrimitiveModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    normalized_key: str
    description: str | None = None
    url: str | None = None
    source_signal_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("entity_id", "canonical_name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("entity fields must be non-empty")
        return text


__all__ = ["Entity"]
