from business.boards._intelligence import (
    BoardScoringProfile,
    evidence_strength,
    freshness_strength,
    related_type_strength,
    source_authority_strength,
    text_signal_score,
)
from business.foundation import BoardCard, BoardType


AI_NEWS_PROFILE = BoardScoringProfile(
    board_type=BoardType.AI_NEWS,
    focus="product_adoption_news",
    feature_weights={
        "release_signal": 0.22,
        "adoption_signal": 0.24,
        "vendor_authority": 0.18,
        "impact_surface": 0.18,
        "evidence_strength": 0.18,
    },
    badge_rules=(
        ("release", "release_signal", 0.45),
        ("adoption", "adoption_signal", 0.45),
        ("official", "vendor_authority", 0.75),
        ("high impact", "impact_surface", 0.65),
    ),
    metric_labels={
        "release_signal": "Release",
        "adoption_signal": "Adoption",
        "vendor_authority": "Vendor",
        "impact_surface": "Impact",
        "evidence_strength": "Evidence",
    },
)


def ai_news_features(card: BoardCard) -> dict[str, float]:
    return {
        "release_signal": max(
            freshness_strength(card),
            text_signal_score(card, ("release", "launch", "announces", "update", "new")),
        ),
        "adoption_signal": text_signal_score(card, ("adopts", "product", "available", "integration", "enterprise")),
        "vendor_authority": source_authority_strength(card),
        "impact_surface": max(related_type_strength(card, "technology"), text_signal_score(card, ("platform", "api", "model", "agent"))),
        "evidence_strength": evidence_strength(card),
    }


def rank_ai_news_card(card: BoardCard):
    features = ai_news_features(card)
    score = sum(features[name] * AI_NEWS_PROFILE.feature_weights[name] for name in AI_NEWS_PROFILE.feature_weights)
    reason = f"AI news ranking emphasizes release/adoption/vendor authority; score={score:.2f}."
    return features, reason, card.score.model_copy(update={"value": min(1.0, round(score, 4))})
