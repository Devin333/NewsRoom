from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from business.boards._intelligence import BoardScoringProfile
from business.foundation import BoardCard, BusinessPolicyProfile
from business.scoring.adapters import (
    apply_scoring_result_to_board_card,
    board_card_scoring_target,
)
from business.scoring.recipes import board_scoring_recipe
from framework.scoring import FeatureVector, ScoringContext, ScoringRuntime


FeatureBuilder = Callable[[BoardCard], FeatureVector]


@dataclass
class BoardScoringService:
    runtime: ScoringRuntime | None = None

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
        result = self.runtime.score_object(
            board_card_scoring_target(card),
            features=feature_builder(card),
            recipe=recipe,
            context=context,
        )
        return apply_scoring_result_to_board_card(card, result, profile=profile, policy=policy)

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
