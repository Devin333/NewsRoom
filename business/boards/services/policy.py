from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from business.boards._intelligence import BoardScoringProfile, enhance_board_run_result
from business.foundation import BoardCard, BoardRunResult, BusinessPolicyProfile
from business.layers.output import BoardOutput


@dataclass(frozen=True)
class BoardPolicyApplicationProfile:
    scoring_profile: BoardScoringProfile
    policy_factory: Callable[[], BusinessPolicyProfile]
    feature_builder: Callable[[BoardCard], dict[str, float]]
    card_presenter: Callable[[list[BoardCard]], list[BoardCard]]


class BoardPolicyApplicationService:
    def __init__(self, profile: BoardPolicyApplicationProfile) -> None:
        self.profile = profile

    def present_output(self, output: BoardOutput) -> BoardOutput:
        return output.model_copy(update={"cards": self.profile.card_presenter(list(output.cards))})

    def apply_to_run_result(self, result: BoardRunResult) -> BoardRunResult:
        return enhance_board_run_result(
            result,
            profile=self.profile.scoring_profile,
            policy=self.profile.policy_factory(),
            feature_builder=self.profile.feature_builder,
        )


__all__ = ["BoardPolicyApplicationProfile", "BoardPolicyApplicationService"]
