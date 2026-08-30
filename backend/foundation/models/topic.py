from __future__ import annotations

from pydantic import Field, field_validator

from backend.foundation.primitives import Confidence, PrimitiveModel


class Topic(PrimitiveModel):
    topic_id: str
    name: str
    normalized_key: str
    parent_topic_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    description: str | None = None
    confidence: Confidence

    @field_validator("topic_id", "name", "normalized_key")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("topic fields must be non-empty")
        return text


__all__ = ["Topic"]
