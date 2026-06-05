from __future__ import annotations

from pydantic import field_validator

from business.foundation.primitives.score import BoundedScore
from business.foundation.taxonomy import ConfidenceMethod


class Confidence(BoundedScore):
    reason: str = ""
    evidence_count: int = 0
    method: ConfidenceMethod = ConfidenceMethod.RULE_BASED

    @field_validator("evidence_count")
    @classmethod
    def _validate_evidence_count(cls, value: int) -> int:
        numeric = int(value)
        if numeric < 0:
            raise ValueError("confidence evidence_count must be non-negative")
        return numeric


__all__ = ["Confidence"]
