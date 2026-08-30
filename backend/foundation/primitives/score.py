from __future__ import annotations

from pydantic import Field, computed_field, field_validator

from backend.foundation.primitives.base import PrimitiveModel
from backend.foundation.taxonomy import ScoreLevel


class ScoreFactor(PrimitiveModel):
    name: str
    value: float
    weight: float = 1.0
    explanation: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("score factor name is required")
        return text

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("score factor value must be between 0 and 1")
        return numeric

    @field_validator("weight")
    @classmethod
    def _validate_weight(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0:
            raise ValueError("score factor weight must be non-negative")
        return numeric


class BoundedScore(PrimitiveModel):
    value: float
    factors: list[ScoreFactor] = Field(default_factory=list)
    explanation: str | None = None

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("score value must be between 0 and 1")
        return round(numeric, 4)

    @computed_field
    @property
    def level(self) -> ScoreLevel:
        return score_level(self.value)


class Score(BoundedScore):
    pass


def score_level(value: float) -> ScoreLevel:
    numeric = float(value)
    if numeric >= 0.8:
        return ScoreLevel.VERY_HIGH
    if numeric >= 0.6:
        return ScoreLevel.HIGH
    if numeric >= 0.4:
        return ScoreLevel.MEDIUM
    if numeric >= 0.2:
        return ScoreLevel.LOW
    return ScoreLevel.VERY_LOW


__all__ = ["BoundedScore", "Score", "ScoreFactor", "score_level"]
