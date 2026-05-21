from __future__ import annotations

from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import ScoringResult
from framework.scoring.recipes import ScoringRecipe


class ScoreCalibrator(Protocol):
    calibrator_id: str

    def calibrate(
        self,
        result: ScoringResult,
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> ScoringResult:
        ...
