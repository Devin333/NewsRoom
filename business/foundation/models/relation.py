from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.models.object_ref import ObjectRef
from business.foundation.primitives import Confidence, PrimitiveModel, ensure_utc
from business.foundation.taxonomy import RelationDirection, RelationType


UTC = _tz.utc


class Relation(PrimitiveModel):
    relation_id: str
    relation_type: RelationType
    source_ref: ObjectRef
    target_ref: ObjectRef
    direction: RelationDirection = RelationDirection.DIRECTED
    evidence_signal_ids: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relation_id")
    @classmethod
    def _validate_relation_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("relation_id is required")
        return text

    @field_validator("evidence_signal_ids", "evidence_claim_ids", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "Relation":
        if not self.evidence_signal_ids and not self.evidence_claim_ids:
            raise ValueError("relation requires evidence_signal_ids or evidence_claim_ids")
        if self.relation_type in {RelationType.IMPLEMENTS, RelationType.PROPOSES, RelationType.ADOPTS} and self.direction != RelationDirection.DIRECTED:
            raise ValueError(f"{self.relation_type.value} relation must be directed")
        if self.relation_type in {RelationType.COMPARES, RelationType.SIMILAR_TO} and self.direction != RelationDirection.UNDIRECTED:
            raise ValueError(f"{self.relation_type.value} relation must be undirected")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


__all__ = ["Relation"]
