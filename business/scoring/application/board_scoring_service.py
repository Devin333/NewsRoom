from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from business.boards._intelligence import BoardScoringProfile
from business.foundation import BoardCard, BusinessPolicyProfile
from business.memory import BusinessMemoryDecisionService
from business.scoring.adapters import (
    apply_scoring_result_to_board_card,
    board_card_scoring_target,
)
from business.scoring.recipes import board_scoring_recipe
from framework.scoring import FeatureVector, ScoringContext, ScoringRecipe, ScoringRuntime


FeatureBuilder = Callable[[BoardCard], FeatureVector]


@dataclass
class BoardScoringService:
    runtime: ScoringRuntime | None = None
    memory_decision_service: BusinessMemoryDecisionService | None = None

    def __post_init__(self) -> None:
        if self.runtime is None:
            self.runtime = ScoringRuntime()

    def score_card(
        self,
        card: BoardCard,
        *,
        profile: BoardScoringProfile,
        policy: BusinessPolicyProfile,
        feature_builder: FeatureBuilder,
        context: ScoringContext | None = None,
    ) -> BoardCard:
        recipe = board_scoring_recipe(profile)
        base_features = feature_builder(card)
        features, memory_used = self._features_with_memory(card, profile=profile, base_features=base_features)
        if memory_used:
            recipe = _recipe_with_memory_weight(recipe)
        result = self.runtime.score_object(
            board_card_scoring_target(card),
            features=features,
            recipe=recipe,
            context=context,
        )
        scored = apply_scoring_result_to_board_card(card, result, profile=profile, policy=policy)
        return scored.model_copy(
            update={
                "ranking_features": {
                    **dict(scored.ranking_features),
                    **{
                        name: features.get(name)
                        for name in features.names()
                        if name.startswith("memory_")
                        or name.endswith("_memory_score")
                        or name.endswith("_penalty")
                        or name == "historical_duplicate_score"
                    },
                },
                "metadata": {
                    **dict(scored.metadata),
                    "memory_features_used": memory_used,
                    "memory_feature_names": [
                        name for name in features.names() if name.endswith("_score") or name.endswith("_penalty")
                    ],
                }
            }
        )

    def score_cards(
        self,
        cards: list[BoardCard],
        *,
        profile: BoardScoringProfile,
        policy: BusinessPolicyProfile,
        feature_builder: FeatureBuilder,
        context: ScoringContext | None = None,
    ) -> list[BoardCard]:
        scored = [
            self.score_card(
                card,
                profile=profile,
                policy=policy,
                feature_builder=feature_builder,
                context=context,
            )
            for card in cards
        ]
        return sorted(scored, key=lambda card: (card.score.value, card.confidence.value, card.title), reverse=True)

    def _features_with_memory(
        self,
        card: BoardCard,
        *,
        profile: BoardScoringProfile,
        base_features: FeatureVector,
    ) -> tuple[FeatureVector, bool]:
        if self.memory_decision_service is None:
            return base_features, False
        memory_features = self.memory_decision_service.memory_features_for_card(
            card,
            board_type=profile.board_type,
        )
        memory_used = bool(memory_features.metadata.get("memory_available")) and bool(
            memory_features.metadata.get("memory_hit_count")
        )
        if not memory_used:
            return base_features, False
        adjusted = base_features.merge(memory_features)
        return adjusted.merge(_memory_decision_overlay(memory_features)), True


def _memory_decision_overlay(
    memory_features: FeatureVector,
) -> FeatureVector:
    return FeatureVector.from_scores(
        {"memory_decision_score": memory_features.get("memory_decision_score", 0.5)},
        source="business_memory",
        metadata={"memory_recipe_overlay": True},
    )


def _recipe_with_memory_weight(recipe: ScoringRecipe) -> ScoringRecipe:
    if "memory_decision_score" in recipe.weights:
        return recipe
    return replace(
        recipe,
        weights={
            **dict(recipe.weights),
            "memory_decision_score": 0.08,
        },
        metadata={
            **dict(recipe.metadata),
            "memory_features_enabled": True,
        },
    )
