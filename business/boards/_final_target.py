from __future__ import annotations

from typing import Any

from business.foundation import (
    BoardCard,
    BoardRunResult,
    BoardType,
    BusinessPolicyProfile,
    BusinessQualityCheck,
    Score,
    build_stable_id,
    quality_snapshot_from_checks,
)
from business.foundation.policies.policy_loader import DEFAULT_BOARD_POLICY_PARAMETERS


def default_board_policy(board_type: BoardType, *, profile_suffix: str = "ranking") -> BusinessPolicyProfile:
    parameters = dict(DEFAULT_BOARD_POLICY_PARAMETERS.get(board_type.value, {}))
    profile_type = f"{board_type.value}_{profile_suffix}"
    return BusinessPolicyProfile(
        profile_id=build_stable_id("policy", profile_type, "v1"),
        profile_type=profile_type,
        version="v1",
        name=f"{board_type.value.replace('_', ' ').title()} {profile_suffix.title()} Policy",
        parameters=parameters,
        status="active",
        metadata={"board_type": board_type.value},
    )


def ranking_payload(card: BoardCard, policy: BusinessPolicyProfile) -> tuple[dict[str, Any], str, Score]:
    features = dict(card.ranking_features)
    features.setdefault("base_score", card.score.value)
    features.setdefault("evidence_count", len(card.evidence_refs))
    features.setdefault("policy_profile_id", policy.profile_id)
    reason = card.ranking_reason or (
        f"Ranked by {policy.profile_type} {policy.version} with score {card.score.value:.2f}."
    )
    return features, reason, card.score


def present_cards(cards: list[BoardCard], policy: BusinessPolicyProfile) -> list[BoardCard]:
    presented: list[BoardCard] = []
    for card in cards:
        features, reason, _score = ranking_payload(card, policy)
        checks = [
            BusinessQualityCheck.create(
                "presented_card_has_evidence",
                passed=bool(card.evidence_refs),
                severity="warning",
                reason="Presented card should preserve evidence references.",
                evidence_refs=list(card.evidence_refs),
            )
        ]
        presented.append(
            card.model_copy(
                update={
                    "ranking_reason": reason,
                    "ranking_features": features,
                    "quality": quality_snapshot_from_checks(checks, score=card.score.value, confidence=card.confidence.value),
                }
            )
        )
    return presented


def attach_presented_cards(result: BoardRunResult, policy: BusinessPolicyProfile) -> BoardRunResult:
    return result.model_copy(update={"cards": present_cards(result.cards, policy)})
