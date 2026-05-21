from __future__ import annotations

from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoringResult
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features import FeatureVector
from framework.scoring.recipes import ScoringRecipe


class ExplanationBuilder(Protocol):
    explainer_id: str

    def explain(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        result: ScoringResult,
        context: ScoringContext,
    ) -> str:
        ...
