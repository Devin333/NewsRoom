from __future__ import annotations

from business.foundation import Score


def ranking_features_from_score(score: Score) -> dict[str, float]:
    return {factor.name: factor.value for factor in score.factors}
