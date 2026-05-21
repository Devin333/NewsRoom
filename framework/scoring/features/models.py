from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoreFactor, clamp_score
from framework.scoring.core.target import ScoringTarget
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class FeatureValue:
    name: str
    value: float
    raw_value: Any = None
    confidence: float = 1.0
    source: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("feature name is required")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "confidence", clamp_score(self.confidence))
        object.__setattr__(self, "evidence_refs", [str(ref) for ref in self.evidence_refs])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_factor(self, *, weight: float = 1.0) -> ScoreFactor:
        return ScoreFactor(
            name=self.name,
            value=self.value,
            weight=weight,
            source=self.source,
            metadata={"feature_confidence": self.confidence, **self.metadata},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "raw_value": to_jsonable(self.raw_value),
            "confidence": self.confidence,
            "source": self.source,
            "evidence_refs": list(self.evidence_refs),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureValue":
        return cls(
            name=str(payload["name"]),
            value=float(payload.get("value", 0.0)),
            raw_value=payload.get("raw_value"),
            confidence=float(payload.get("confidence", 1.0)),
            source=str(payload["source"]) if payload.get("source") is not None else None,
            evidence_refs=[str(ref) for ref in payload.get("evidence_refs") or []],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class FeatureVector:
    values: dict[str, FeatureValue] = field(default_factory=dict)
    missing_features: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = {
            str(name): value if isinstance(value, FeatureValue) else FeatureValue.from_dict(dict(value))
            for name, value in dict(self.values or {}).items()
        }
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "missing_features", [str(name) for name in self.missing_features])
        object.__setattr__(self, "evidence_refs", [str(ref) for ref in self.evidence_refs])
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_scores(
        cls,
        scores: dict[str, float],
        *,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "FeatureVector":
        return cls(
            values={
                str(name): FeatureValue(name=str(name), value=float(value), source=source)
                for name, value in dict(scores or {}).items()
            },
            metadata=dict(metadata or {}),
        )

    def get(self, name: str, default: float = 0.0) -> float:
        value = self.values.get(name)
        return float(value.value) if value is not None else float(default)

    def require(self, name: str) -> float:
        if name not in self.values:
            raise KeyError(f"missing required feature: {name}")
        return float(self.values[name].value)

    def names(self) -> list[str]:
        return sorted(self.values)

    def as_float_dict(self) -> dict[str, float]:
        return {name: float(value.value) for name, value in self.values.items()}

    def merge(self, other: "FeatureVector") -> "FeatureVector":
        return FeatureVector(
            values={**self.values, **other.values},
            missing_features=list(dict.fromkeys([*self.missing_features, *other.missing_features])),
            evidence_refs=list(dict.fromkeys([*self.evidence_refs, *other.evidence_refs])),
            metadata={**self.metadata, **other.metadata},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": {name: value.to_dict() for name, value in self.values.items()},
            "missing_features": list(self.missing_features),
            "evidence_refs": list(self.evidence_refs),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureVector":
        return cls(
            values={
                str(name): FeatureValue.from_dict(dict(value))
                for name, value in dict(payload.get("values") or {}).items()
            },
            missing_features=[str(name) for name in payload.get("missing_features") or []],
            evidence_refs=[str(ref) for ref in payload.get("evidence_refs") or []],
            metadata=dict(payload.get("metadata") or {}),
        )


class FeatureProvider(Protocol):
    provider_id: str

    def build(
        self,
        target: ScoringTarget,
        context: ScoringContext,
    ) -> FeatureVector:
        ...


class FeatureNormalizer(Protocol):
    normalizer_id: str

    def normalize(
        self,
        features: FeatureVector,
        context: ScoringContext,
    ) -> FeatureVector:
        ...
