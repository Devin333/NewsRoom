from __future__ import annotations

from pydantic import field_validator

from business.foundation.models.object_ref import ObjectRef
from business.foundation.primitives import Confidence, PrimitiveModel, TextSpan
from business.foundation.taxonomy import ClaimModality, ClaimPolarity, ClaimType


class Claim(PrimitiveModel):
    claim_id: str
    signal_id: str
    claim_type: ClaimType
    text: str
    subject_ref: ObjectRef | None = None
    predicate: str | None = None
    object_ref: ObjectRef | None = None
    polarity: ClaimPolarity = ClaimPolarity.NEUTRAL
    modality: ClaimModality = ClaimModality.ASSERTED
    evidence_span: TextSpan | None = None
    confidence: Confidence

    @field_validator("claim_id", "signal_id", "text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("claim fields must be non-empty")
        return text


__all__ = ["Claim"]
