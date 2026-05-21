from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.models import RankingItem, RankingResult, ScoringResult
from framework.scoring.recipes import ScoringRecipe


class Ranker(Protocol):
    ranker_id: str

    def rank(
        self,
        results: list[ScoringResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        ...


@dataclass(frozen=True)
class PriorityRanker:
    ranker_id: str = "priority"

    def rank(
        self,
        results: list[ScoringResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        dropped_results = [result for result in results if result.blocked]
        kept_results = [result for result in results if not result.blocked]
        kept_results.sort(key=lambda result: (-result.final_score, -result.score.confidence, result.target_id))
        return RankingResult(
            recipe_id=recipe.recipe_id,
            items=_items(kept_results),
            dropped_items=_items(dropped_results),
            metadata={"ranker_id": self.ranker_id},
        )


@dataclass(frozen=True)
class DiversityRanker:
    ranker_id: str = "diversity"
    diversity_key: str = "source"

    def rank(
        self,
        results: list[ScoringResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        key = str(recipe.params.get("diversity_key") or self.diversity_key)
        max_per_key = max(1, int(recipe.params.get("max_per_diversity_key", 2)))
        priority = PriorityRanker().rank(results, recipe=recipe, context=context)
        counts: dict[str, int] = {}
        kept: list[ScoringResult] = []
        dropped = [item.result for item in priority.dropped_items]
        for item in priority.items:
            value = str(item.result.metadata.get(key) or item.result.score.metadata.get(key) or item.result.target_id)
            count = counts.get(value, 0)
            if count >= max_per_key:
                dropped.append(item.result)
                continue
            counts[value] = count + 1
            kept.append(item.result)
        return RankingResult(
            recipe_id=recipe.recipe_id,
            items=_items(kept),
            dropped_items=_items(dropped),
            metadata={"ranker_id": self.ranker_id, "diversity_key": key, "max_per_key": max_per_key},
        )


@dataclass(frozen=True)
class DedupRanker:
    ranker_id: str = "dedup"
    dedup_key: str = "canonical_id"

    def rank(
        self,
        results: list[ScoringResult],
        *,
        recipe: ScoringRecipe,
        context: ScoringContext,
    ) -> RankingResult:
        key = str(recipe.params.get("dedup_key") or self.dedup_key)
        best_by_key: dict[str, ScoringResult] = {}
        dropped: list[ScoringResult] = []
        for result in results:
            value = str(result.metadata.get(key) or result.score.metadata.get(key) or result.target_id)
            current = best_by_key.get(value)
            if current is None or (result.final_score, result.score.confidence) > (current.final_score, current.score.confidence):
                if current is not None:
                    dropped.append(current)
                best_by_key[value] = result
            else:
                dropped.append(result)
        priority = PriorityRanker().rank(list(best_by_key.values()), recipe=recipe, context=context)
        return RankingResult(
            recipe_id=recipe.recipe_id,
            items=priority.items,
            dropped_items=[*priority.dropped_items, *_items(dropped)],
            metadata={"ranker_id": self.ranker_id, "dedup_key": key},
        )


def _items(results: list[ScoringResult]) -> list[RankingItem]:
    return [
        RankingItem(
            target_id=result.target_id,
            target_type=result.target_type,
            rank=index,
            score=result.final_score,
            result=result,
        )
        for index, result in enumerate(results, start=1)
    ]
