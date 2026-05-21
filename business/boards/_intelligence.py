from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from business.foundation import (
    Badge,
    BoardCard,
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessPolicyProfile,
    BusinessQualityCheck,
    BusinessQualitySnapshot,
    Confidence,
    DisplayMetric,
    Score,
    quality_snapshot_from_checks,
)


@dataclass(frozen=True)
class BoardScoringProfile:
    board_type: BoardType
    focus: str
    feature_weights: dict[str, float]
    badge_rules: tuple[tuple[str, str, float], ...]
    metric_labels: dict[str, str]


def enhance_board_run_result(
    result: BoardRunResult,
    *,
    profile: BoardScoringProfile,
    policy: BusinessPolicyProfile,
    feature_builder: Callable[[BoardCard], dict[str, float]],
) -> BoardRunResult:
    cards = [_enhance_card(card, profile=profile, policy=policy, feature_builder=feature_builder) for card in result.cards]
    cards.sort(key=lambda card: (card.score.value, card.confidence.value, card.title), reverse=True)
    quality_summary = _quality_summary(cards, profile=profile, base=result.quality_summary)
    feedback = list(result.feedback_candidates)
    feedback.extend(_feedback_from_quality(quality_summary, result, policy))
    metadata = {
        **dict(result.metadata),
        "board_intelligence": {
            "focus": profile.focus,
            "feature_weights": dict(profile.feature_weights),
            "policy_profile_id": policy.profile_id,
            "policy_profile_version": policy.version,
        },
    }
    return result.model_copy(
        update={
            "cards": cards,
            "quality_summary": quality_summary,
            "feedback_candidates": feedback,
            "metadata": metadata,
        }
    )


def enhance_board_cards(
    cards: list[BoardCard],
    *,
    profile: BoardScoringProfile,
    policy: BusinessPolicyProfile,
    feature_builder: Callable[[BoardCard], dict[str, float]],
) -> list[BoardCard]:
    enhanced = [_enhance_card(card, profile=profile, policy=policy, feature_builder=feature_builder) for card in cards]
    return sorted(enhanced, key=lambda card: (card.score.value, card.confidence.value, card.title), reverse=True)


def text_signal_score(card: BoardCard, keywords: tuple[str, ...]) -> float:
    text = _card_text(card)
    hits = sum(1 for keyword in keywords if keyword in text)
    return _clamp(hits / max(1, len(keywords[:4]) or 1))


def metadata_number(card: BoardCard, *keys: str) -> float:
    for key in keys:
        value = card.metadata.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def metric_value(card: BoardCard, label: str) -> float:
    label_key = label.casefold()
    for metric in card.metrics:
        if metric.label.casefold() != label_key:
            continue
        value = metric.value
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except ValueError:
            return 0.0
    return 0.0


def normalized_count(value: float, divisor: float) -> float:
    if divisor <= 0:
        return 0.0
    return _clamp(value / divisor)


def evidence_strength(card: BoardCard) -> float:
    return _clamp(0.25 + len(card.evidence_refs) * 0.25 + len(card.relation_refs) * 0.10)


def relation_strength(card: BoardCard) -> float:
    return normalized_count(metric_value(card, "Relations") + len(card.relation_refs), 4.0)


def related_type_strength(card: BoardCard, object_type: str) -> float:
    return normalized_count(sum(1 for ref in card.related_refs if ref.object_type.value == object_type), 3.0)


def freshness_strength(card: BoardCard) -> float:
    if card.published_at is None:
        return 0.5
    age_seconds = max(0.0, (card.generated_at - card.published_at).total_seconds())
    age_days = age_seconds / 86400.0
    return _clamp(1.0 - age_days / 14.0)


def source_authority_strength(card: BoardCard) -> float:
    source_names = " ".join(ref.source_name for ref in card.evidence_refs).casefold()
    if any(name in source_names for name in ("openai", "anthropic", "google", "deepmind", "microsoft", "meta", "nvidia")):
        return 1.0
    return _clamp(0.45 + len(card.evidence_refs) * 0.15)


def _enhance_card(
    card: BoardCard,
    *,
    profile: BoardScoringProfile,
    policy: BusinessPolicyProfile,
    feature_builder: Callable[[BoardCard], dict[str, float]],
) -> BoardCard:
    raw_features = feature_builder(card)
    features = {key: _clamp(value) for key, value in raw_features.items()}
    weighted_score = _weighted_score(features, profile.feature_weights, fallback=card.score.value)
    score = Score(
        value=weighted_score,
        factors=[
            {"name": key, "value": value, "weight": profile.feature_weights.get(key, 0.0)}
            for key, value in sorted(features.items())
        ],
    )
    ranking_features = {
        **dict(card.ranking_features),
        **features,
        "board_focus": profile.focus,
        "policy_profile_id": policy.profile_id,
        "weighted_score": weighted_score,
    }
    checks = _card_quality_checks(card, features=features, profile=profile)
    quality = quality_snapshot_from_checks(
        checks,
        score=weighted_score,
        confidence=card.confidence.value,
    )
    return card.model_copy(
        update={
            "score": score,
            "confidence": Confidence(value=min(1.0, max(card.confidence.value, weighted_score * 0.85)), factors=list(card.confidence.factors)),
            "ranking_features": ranking_features,
            "ranking_reason": _ranking_reason(profile, policy, features, weighted_score),
            "badges": _badges(card, profile, features),
            "metrics": _metrics(card, profile, features),
            "quality": quality,
            "metadata": {
                **dict(card.metadata),
                "board_focus": profile.focus,
                "board_specific_features": features,
                "policy_profile_id": policy.profile_id,
                "policy_profile_version": policy.version,
            },
        }
    )


def _weighted_score(features: dict[str, float], weights: dict[str, float], *, fallback: float) -> float:
    total_weight = sum(max(0.0, weight) for weight in weights.values())
    if total_weight <= 0:
        return _clamp(fallback)
    weighted = sum(_clamp(features.get(name, 0.0)) * max(0.0, weight) for name, weight in weights.items())
    return round(_clamp(weighted / total_weight), 4)


def _ranking_reason(
    profile: BoardScoringProfile,
    policy: BusinessPolicyProfile,
    features: dict[str, float],
    score: float,
) -> str:
    top_features = sorted(features.items(), key=lambda item: item[1], reverse=True)[:3]
    rendered = ", ".join(f"{name}={value:.2f}" for name, value in top_features)
    return f"{profile.focus} ranking via {policy.profile_type} {policy.version}: {rendered}; score={score:.2f}."


def _badges(card: BoardCard, profile: BoardScoringProfile, features: dict[str, float]) -> list[Badge]:
    badges = list(card.badges)
    existing = {badge.label for badge in badges}
    for label, feature, threshold in profile.badge_rules:
        if features.get(feature, 0.0) >= threshold and label not in existing:
            badges.append(Badge(label=label, tone="positive", value=f"{features[feature]:.2f}"))
            existing.add(label)
    if profile.focus not in existing:
        badges.append(Badge(label=profile.focus, tone="neutral"))
    return badges


def _metrics(card: BoardCard, profile: BoardScoringProfile, features: dict[str, float]) -> list[DisplayMetric]:
    metrics = list(card.metrics)
    existing = {metric.label.casefold() for metric in metrics}
    for feature, label in profile.metric_labels.items():
        if label.casefold() in existing:
            continue
        metrics.append(DisplayMetric(label=label, value=round(features.get(feature, 0.0), 3)))
        existing.add(label.casefold())
    return metrics


def _card_quality_checks(
    card: BoardCard,
    *,
    features: dict[str, float],
    profile: BoardScoringProfile,
) -> list[BusinessQualityCheck]:
    return [
        BusinessQualityCheck.create(
            f"{profile.board_type.value}_has_evidence",
            passed=bool(card.evidence_refs),
            severity="error",
            reason="Board-specific card must preserve evidence references.",
            observed={"evidence_count": len(card.evidence_refs)},
            evidence_refs=list(card.evidence_refs),
        ),
        BusinessQualityCheck.create(
            f"{profile.board_type.value}_has_distinct_features",
            passed=bool(features) and len(features) >= 3,
            severity="error",
            reason="Board-specific ranking requires at least three explainable features.",
            observed={"feature_count": len(features), "features": sorted(features)},
        ),
        BusinessQualityCheck.create(
            f"{profile.board_type.value}_policy_threshold",
            passed=max(features.values() or [0.0]) >= 0.35,
            severity="warning",
            reason="Weak board-specific signal should be reviewed.",
            observed={"max_feature": max(features.values() or [0.0])},
        ),
    ]


def _quality_summary(
    cards: list[BoardCard],
    *,
    profile: BoardScoringProfile,
    base: BusinessQualitySnapshot | None,
) -> BusinessQualitySnapshot:
    checks = list(base.checks if base is not None else [])
    checks.extend(
        [
            BusinessQualityCheck.create(
                f"{profile.board_type.value}_cards_sorted_by_board_score",
                passed=cards == sorted(cards, key=lambda card: (card.score.value, card.confidence.value, card.title), reverse=True),
                severity="error",
                reason="Board cards must be sorted by board-specific score.",
                observed={"card_count": len(cards)},
            ),
            BusinessQualityCheck.create(
                f"{profile.board_type.value}_cards_have_board_focus",
                passed=all(card.metadata.get("board_focus") == profile.focus for card in cards),
                severity="error",
                reason="Presented cards must include board-specific focus metadata.",
                observed={"focus": profile.focus, "card_count": len(cards)},
            ),
        ]
    )
    passed = sum(1 for check in checks if check.passed)
    score = 1.0 if not checks else round(passed / len(checks), 4)
    return quality_snapshot_from_checks(checks, score=score, confidence=0.85)


def _feedback_from_quality(
    quality: BusinessQualitySnapshot,
    result: BoardRunResult,
    policy: BusinessPolicyProfile,
) -> list[BusinessFeedbackEvent]:
    events: list[BusinessFeedbackEvent] = []
    for check in quality.checks:
        if check.passed:
            continue
        events.append(
            BusinessFeedbackEvent.create(
                target_object_type="board_run",
                target_object_id=result.run_id,
                target_layer="board",
                board_type=result.board_type.value,
                feedback_type=check.check_type,
                severity=check.severity,
                observed=check.observed,
                expected=check.expected,
                error_tags=[check.check_type],
                evidence_refs=list(check.evidence_refs),
                related_policy_profile_id=policy.profile_id,
                related_policy_profile_version=policy.version,
                metadata={"source": "board_intelligence_hardening"},
            )
        )
    return events


def _card_text(card: BoardCard) -> str:
    parts = [
        card.title,
        card.subtitle or "",
        card.summary,
        " ".join(badge.label for badge in card.badges),
        " ".join(str(value) for value in card.metadata.values() if isinstance(value, (str, int, float))),
    ]
    return " ".join(parts).casefold()


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)
