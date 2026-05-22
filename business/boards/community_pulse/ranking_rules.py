from business.boards._intelligence import (
    BoardScoringProfile,
    evidence_strength,
    freshness_strength,
    normalized_count,
    related_type_strength,
    relation_strength,
    text_signal_score,
)
from business.foundation import BoardCard, BoardType


COMMUNITY_PULSE_PROFILE = BoardScoringProfile(
    board_type=BoardType.COMMUNITY_PULSE,
    focus="community_discussion_pulse",
    feature_weights={
        "discussion_heat": 0.24,
        "sentiment_divergence": 0.20,
        "problem_signal": 0.20,
        "source_diversity": 0.18,
        "freshness": 0.18,
    },
    badge_rules=(
        ("hot topic", "discussion_heat", 0.55),
        ("mixed sentiment", "sentiment_divergence", 0.45),
        ("problem signal", "problem_signal", 0.45),
        ("fresh", "freshness", 0.65),
    ),
    metric_labels={
        "discussion_heat": "Heat",
        "sentiment_divergence": "Sentiment Divergence",
        "problem_signal": "Problem Signal",
        "source_diversity": "Source Diversity",
        "freshness": "Freshness",
    },
)


def community_pulse_features(card: BoardCard) -> dict[str, float]:
    positive = text_signal_score(card, ("great", "useful", "works", "love", "adopted"))
    negative = text_signal_score(card, ("bug", "issue", "broken", "risk", "concern", "tradeoff"))
    return {
        "discussion_heat": max(relation_strength(card), text_signal_score(card, ("discuss", "thread", "comments", "hn", "reddit"))),
        "sentiment_divergence": min(1.0, positive + negative),
        "problem_signal": max(negative, text_signal_score(card, ("reliability", "cost", "latency", "security", "quality"))),
        "source_diversity": max(normalized_count(len(card.evidence_refs), 3.0), related_type_strength(card, "community_thread")),
        "freshness": max(freshness_strength(card), evidence_strength(card) * 0.6),
    }


def rank_community_card(card: BoardCard):
    features = community_pulse_features(card)
    score = sum(features[name] * COMMUNITY_PULSE_PROFILE.feature_weights[name] for name in COMMUNITY_PULSE_PROFILE.feature_weights)
    reason = f"Community pulse ranking emphasizes discussion heat/sentiment/problem signals; score={score:.2f}."
    return features, reason, card.score.model_copy(update={"value": min(1.0, round(score, 4))})
