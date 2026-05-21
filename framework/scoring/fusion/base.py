from __future__ import annotations

from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import RankingResult
from framework.scoring.recipes import ScoringRecipe


class RankFusion(Protocol):
    fusion_id: str

    def fuse(
        self,
        rankings: list[RankingResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        ...
