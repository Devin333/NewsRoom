from __future__ import annotations

from dataclasses import dataclass, replace

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import RankingItem, RankingResult, ScoringResult, clamp_score
from framework.scoring.recipes import ScoringRecipe


@dataclass(frozen=True)
class ReciprocalRankFusion:
    fusion_id: str = "rrf"
    k: int = 60

    def fuse(
        self,
        rankings: list[RankingResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        scores: dict[str, float] = {}
        results: dict[str, ScoringResult] = {}
        for ranking in rankings:
            for item in ranking.items:
                scores[item.target_id] = scores.get(item.target_id, 0.0) + 1.0 / (self.k + max(1, item.rank))
                results.setdefault(item.target_id, item.result)
        return _ranking_from_scores(recipe.recipe_id, scores, results, fusion_id=self.fusion_id)


@dataclass(frozen=True)
class BordaFusion:
    fusion_id: str = "borda"

    def fuse(
        self,
        rankings: list[RankingResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        scores: dict[str, float] = {}
        results: dict[str, ScoringResult] = {}
        for ranking in rankings:
            length = len(ranking.items)
            for item in ranking.items:
                scores[item.target_id] = scores.get(item.target_id, 0.0) + max(0, length - item.rank + 1)
                results.setdefault(item.target_id, item.result)
        return _ranking_from_scores(recipe.recipe_id, scores, results, fusion_id=self.fusion_id)


@dataclass(frozen=True)
class WeightedScoreFusion:
    fusion_id: str = "weighted_score_fusion"
    weights: dict[str, float] | None = None

    def fuse(
        self,
        rankings: list[RankingResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        configured = dict(self.weights or recipe.params.get("ranking_weights") or {})
        scores: dict[str, float] = {}
        totals: dict[str, float] = {}
        results: dict[str, ScoringResult] = {}
        for index, ranking in enumerate(rankings):
            ranking_weight = float(configured.get(ranking.recipe_id, configured.get(str(index), 1.0)))
            for item in ranking.items:
                scores[item.target_id] = scores.get(item.target_id, 0.0) + item.score * ranking_weight
                totals[item.target_id] = totals.get(item.target_id, 0.0) + ranking_weight
                results.setdefault(item.target_id, item.result)
        averaged = {target_id: score / totals[target_id] for target_id, score in scores.items() if totals[target_id] > 0}
        return _ranking_from_scores(recipe.recipe_id, averaged, results, fusion_id=self.fusion_id)


def _ranking_from_scores(
    recipe_id: str,
    scores: dict[str, float],
    results: dict[str, ScoringResult],
    *,
    fusion_id: str,
) -> RankingResult:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if ordered:
        max_score = max(score for _, score in ordered) or 1.0
    else:
        max_score = 1.0
    items: list[RankingItem] = []
    for rank, (target_id, score) in enumerate(ordered, start=1):
        result = results[target_id]
        normalized = clamp_score(score / max_score)
        fused_result = replace(
            result,
            score=result.score.with_final_score(normalized),
            metadata={**result.metadata, "fusion_score": score, "fusion_id": fusion_id},
        )
        items.append(
            RankingItem(
                target_id=target_id,
                target_type=result.target_type,
                rank=rank,
                score=normalized,
                result=fused_result,
            )
        )
    return RankingResult(recipe_id=recipe_id, items=items, metadata={"fusion_id": fusion_id})
