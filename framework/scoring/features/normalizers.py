from __future__ import annotations

from dataclasses import dataclass, field

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import clamp_score
from framework.scoring.features.models import FeatureValue, FeatureVector


@dataclass(frozen=True)
class ClampFeatureNormalizer:
    normalizer_id: str = "clamp"
    min_value: float = 0.0
    max_value: float = 1.0

    def normalize(self, features: FeatureVector, context: ScoringContext) -> FeatureVector:
        lower = float(self.min_value)
        upper = float(self.max_value)
        if upper < lower:
            lower, upper = upper, lower
        span = upper - lower
        normalized: dict[str, FeatureValue] = {}
        for name, feature in features.values.items():
            value = feature.value
            if span and (lower != 0.0 or upper != 1.0):
                value = (value - lower) / span
            normalized[name] = FeatureValue(
                name=feature.name,
                value=clamp_score(value),
                raw_value=feature.raw_value if feature.raw_value is not None else feature.value,
                confidence=feature.confidence,
                source=feature.source,
                evidence_refs=list(feature.evidence_refs),
                metadata=dict(feature.metadata),
            )
        return FeatureVector(
            values=normalized,
            missing_features=list(features.missing_features),
            evidence_refs=list(features.evidence_refs),
            metadata=dict(features.metadata),
        )


@dataclass(frozen=True)
class MinMaxFeatureNormalizer:
    normalizer_id: str = "min_max"
    ranges: dict[str, tuple[float, float]] = field(default_factory=dict)

    def normalize(self, features: FeatureVector, context: ScoringContext) -> FeatureVector:
        normalized: dict[str, FeatureValue] = {}
        for name, feature in features.values.items():
            if name not in self.ranges:
                normalized[name] = feature
                continue
            min_value, max_value = self.ranges[name]
            span = float(max_value) - float(min_value)
            value = 0.0 if span <= 0.0 else (feature.value - float(min_value)) / span
            normalized[name] = FeatureValue(
                name=feature.name,
                value=clamp_score(value),
                raw_value=feature.raw_value if feature.raw_value is not None else feature.value,
                confidence=feature.confidence,
                source=feature.source,
                evidence_refs=list(feature.evidence_refs),
                metadata=dict(feature.metadata),
            )
        return FeatureVector(
            values=normalized,
            missing_features=list(features.missing_features),
            evidence_refs=list(features.evidence_refs),
            metadata=dict(features.metadata),
        )
