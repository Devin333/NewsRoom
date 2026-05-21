from __future__ import annotations

from dataclasses import dataclass, field

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features.models import FeatureVector


@dataclass(frozen=True)
class StaticFeatureProvider:
    provider_id: str = "static"
    features_by_target_id: dict[str, FeatureVector] = field(default_factory=dict)
    default_features: FeatureVector | None = None

    def build(
        self,
        target: ScoringTarget,
        context: ScoringContext,
    ) -> FeatureVector:
        return self.features_by_target_id.get(target.target_id) or self.default_features or FeatureVector()
