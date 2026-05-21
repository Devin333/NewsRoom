from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from framework.shared.json import to_jsonable


class ScoreLevel(str, Enum):
    BLOCKED = "blocked"
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

    @classmethod
    def from_score(cls, value: float, *, blocked: bool = False) -> "ScoreLevel":
        if blocked:
            return cls.BLOCKED
        score = clamp_score(value)
        if score < 0.2:
            return cls.VERY_LOW
        if score < 0.4:
            return cls.LOW
        if score < 0.6:
            return cls.MEDIUM
        if score < 0.8:
            return cls.HIGH
        return cls.VERY_HIGH


@dataclass(frozen=True)
class ScoreValue:
    value: float
    level: ScoreLevel | None = None

    def __post_init__(self) -> None:
        value = clamp_score(self.value)
        level = self.level if isinstance(self.level, ScoreLevel) else (
            ScoreLevel(str(self.level)) if self.level is not None else ScoreLevel.from_score(value)
        )
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "level", level)

    @classmethod
    def clamp(cls, value: float) -> float:
        return clamp_score(value)

    @classmethod
    def from_raw(cls, value: float) -> "ScoreValue":
        return cls(value=value)

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "level": self.level.value if self.level else None}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreValue":
        return cls(
            value=float(payload.get("value", 0.0)),
            level=ScoreLevel(payload["level"]) if payload.get("level") else None,
        )


@dataclass(frozen=True)
class ScoreFactor:
    name: str
    value: float
    weight: float = 1.0
    contribution: float | None = None
    source: str | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("score factor name is required")
        weight = float(self.weight)
        if weight < 0.0:
            raise ValueError("score factor weight must be non-negative")
        value = clamp_score(self.value)
        contribution = float(self.contribution) if self.contribution is not None else value * weight
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "weight", weight)
        object.__setattr__(self, "contribution", contribution)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "contribution": self.contribution,
            "source": self.source,
            "explanation": self.explanation,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreFactor":
        return cls(
            name=str(payload["name"]),
            value=float(payload.get("value", 0.0)),
            weight=float(payload.get("weight", 1.0)),
            contribution=(
                float(payload["contribution"]) if payload.get("contribution") is not None else None
            ),
            source=str(payload["source"]) if payload.get("source") is not None else None,
            explanation=(
                str(payload["explanation"]) if payload.get("explanation") is not None else None
            ),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScoreBundle:
    raw_score: float
    gated_score: float
    calibrated_score: float
    final_score: float
    channels: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    risk: float = 0.0
    level: ScoreLevel | None = None
    factors: list[ScoreFactor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        final_score = clamp_score(self.final_score)
        level = self.level if isinstance(self.level, ScoreLevel) else (
            ScoreLevel(str(self.level)) if self.level is not None else ScoreLevel.from_score(final_score)
        )
        object.__setattr__(self, "raw_score", clamp_score(self.raw_score))
        object.__setattr__(self, "gated_score", clamp_score(self.gated_score))
        object.__setattr__(self, "calibrated_score", clamp_score(self.calibrated_score))
        object.__setattr__(self, "final_score", final_score)
        object.__setattr__(
            self,
            "channels",
            {str(name): clamp_score(value) for name, value in dict(self.channels or {}).items()},
        )
        object.__setattr__(self, "confidence", clamp_score(self.confidence))
        object.__setattr__(self, "risk", clamp_score(self.risk))
        object.__setattr__(self, "level", level)
        object.__setattr__(
            self,
            "factors",
            [factor if isinstance(factor, ScoreFactor) else ScoreFactor.from_dict(factor) for factor in self.factors],
        )
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_raw_score(
        cls,
        raw_score: float,
        *,
        channels: dict[str, float] | None = None,
        confidence: float = 0.0,
        risk: float = 0.0,
        factors: list[ScoreFactor] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ScoreBundle":
        score = clamp_score(raw_score)
        return cls(
            raw_score=score,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            channels=dict(channels or {}),
            confidence=confidence,
            risk=risk,
            factors=list(factors or []),
            metadata=dict(metadata or {}),
        )

    def with_gated_score(self, value: float) -> "ScoreBundle":
        score = clamp_score(value)
        return replace(
            self,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            level=ScoreLevel.from_score(score),
        )

    def with_calibrated_score(self, value: float) -> "ScoreBundle":
        score = clamp_score(value)
        return replace(
            self,
            calibrated_score=score,
            final_score=score,
            level=ScoreLevel.from_score(score),
        )

    def with_final_score(self, value: float) -> "ScoreBundle":
        score = clamp_score(value)
        return replace(
            self,
            gated_score=score,
            calibrated_score=score,
            final_score=score,
            level=ScoreLevel.from_score(score),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "gated_score": self.gated_score,
            "calibrated_score": self.calibrated_score,
            "final_score": self.final_score,
            "channels": dict(self.channels),
            "confidence": self.confidence,
            "risk": self.risk,
            "level": self.level.value if self.level else None,
            "factors": [factor.to_dict() for factor in self.factors],
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreBundle":
        return cls(
            raw_score=float(payload.get("raw_score", 0.0)),
            gated_score=float(payload.get("gated_score", payload.get("raw_score", 0.0))),
            calibrated_score=float(payload.get("calibrated_score", payload.get("final_score", 0.0))),
            final_score=float(payload.get("final_score", 0.0)),
            channels={str(key): float(value) for key, value in dict(payload.get("channels") or {}).items()},
            confidence=float(payload.get("confidence", 0.0)),
            risk=float(payload.get("risk", 0.0)),
            level=ScoreLevel(payload["level"]) if payload.get("level") else None,
            factors=[
                factor if isinstance(factor, ScoreFactor) else ScoreFactor.from_dict(dict(factor))
                for factor in payload.get("factors") or []
            ],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScoringResult:
    target_id: str
    target_type: str
    recipe_id: str
    score: ScoreBundle
    gates: list[Any] = field(default_factory=list)
    explanation: str = ""
    trace: Any | None = None
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    review_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", str(self.target_id))
        object.__setattr__(self, "target_type", str(self.target_type))
        object.__setattr__(self, "recipe_id", str(self.recipe_id))
        if not isinstance(self.score, ScoreBundle):
            object.__setattr__(self, "score", ScoreBundle.from_dict(dict(self.score)))
        object.__setattr__(self, "gates", list(self.gates or []))
        object.__setattr__(self, "warnings", [str(warning) for warning in self.warnings])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def final_score(self) -> float:
        return self.score.final_score

    def with_score(self, score: ScoreBundle) -> "ScoringResult":
        return replace(self, score=score)

    def with_explanation(self, explanation: str) -> "ScoringResult":
        return replace(self, explanation=str(explanation))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "recipe_id": self.recipe_id,
            "score": self.score.to_dict(),
            "gates": [_to_dict(gate) for gate in self.gates],
            "explanation": self.explanation,
            "trace": _to_dict(self.trace) if self.trace is not None else None,
            "warnings": list(self.warnings),
            "blocked": self.blocked,
            "review_required": self.review_required,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringResult":
        return cls(
            target_id=str(payload["target_id"]),
            target_type=str(payload["target_type"]),
            recipe_id=str(payload["recipe_id"]),
            score=ScoreBundle.from_dict(dict(payload["score"])),
            gates=list(payload.get("gates") or []),
            explanation=str(payload.get("explanation") or ""),
            trace=payload.get("trace"),
            warnings=[str(warning) for warning in payload.get("warnings") or []],
            blocked=bool(payload.get("blocked", False)),
            review_required=bool(payload.get("review_required", False)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RankingItem:
    target_id: str
    target_type: str
    rank: int
    score: float
    result: ScoringResult
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", str(self.target_id))
        object.__setattr__(self, "target_type", str(self.target_type))
        object.__setattr__(self, "rank", int(self.rank))
        object.__setattr__(self, "score", clamp_score(self.score))
        if not isinstance(self.result, ScoringResult):
            object.__setattr__(self, "result", ScoringResult.from_dict(dict(self.result)))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "target_type": self.target_type,
            "rank": self.rank,
            "score": self.score,
            "result": self.result.to_dict(),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RankingItem":
        return cls(
            target_id=str(payload["target_id"]),
            target_type=str(payload["target_type"]),
            rank=int(payload["rank"]),
            score=float(payload.get("score", 0.0)),
            result=ScoringResult.from_dict(dict(payload["result"])),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RankingResult:
    recipe_id: str
    items: list[RankingItem]
    dropped_items: list[RankingItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", str(self.recipe_id))
        object.__setattr__(
            self,
            "items",
            [item if isinstance(item, RankingItem) else RankingItem.from_dict(dict(item)) for item in self.items],
        )
        object.__setattr__(
            self,
            "dropped_items",
            [
                item if isinstance(item, RankingItem) else RankingItem.from_dict(dict(item))
                for item in self.dropped_items
            ],
        )
        object.__setattr__(self, "warnings", [str(warning) for warning in self.warnings])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def top(self, limit: int) -> list[RankingItem]:
        return list(self.items[: max(0, int(limit))])

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "items": [item.to_dict() for item in self.items],
            "dropped_items": [item.to_dict() for item in self.dropped_items],
            "warnings": list(self.warnings),
            "trace": _to_dict(self.trace) if self.trace is not None else None,
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RankingResult":
        return cls(
            recipe_id=str(payload["recipe_id"]),
            items=[RankingItem.from_dict(dict(item)) for item in payload.get("items") or []],
            dropped_items=[
                RankingItem.from_dict(dict(item)) for item in payload.get("dropped_items") or []
            ],
            warnings=[str(warning) for warning in payload.get("warnings") or []],
            trace=payload.get("trace"),
            metadata=dict(payload.get("metadata") or {}),
        )


def clamp_score(value: float) -> float:
    numeric = float(value)
    if math.isnan(numeric):
        return 0.0
    if numeric == math.inf:
        return 1.0
    if numeric == -math.inf:
        return 0.0
    return max(0.0, min(1.0, numeric))


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    cleaned = {str(name): max(0.0, float(weight)) for name, weight in dict(weights or {}).items()}
    total = sum(cleaned.values())
    if total <= 0.0:
        return {name: 0.0 for name in cleaned}
    return {name: weight / total for name, weight in cleaned.items()}


def score_level(value: float, *, blocked: bool = False) -> ScoreLevel:
    return ScoreLevel.from_score(value, blocked=blocked)


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    return to_jsonable(value)
