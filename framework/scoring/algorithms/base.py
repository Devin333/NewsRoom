from __future__ import annotations

from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoreBundle
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features import FeatureVector
from framework.scoring.recipes import ScoringRecipe


class ScoringAlgorithm(Protocol):
    algorithm_id: str
    scorer_id: str

    def score(
        self,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoreBundle:
        ...


Scorer = ScoringAlgorithm
