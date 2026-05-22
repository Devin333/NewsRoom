from business.boards._intelligence import (
    BoardScoringProfile,
    evidence_strength,
    normalized_count,
    related_type_strength,
    relation_strength,
    text_signal_score,
)
from business.foundation import BoardCard, BoardType


PROJECT_RADAR_PROFILE = BoardScoringProfile(
    board_type=BoardType.PROJECT_RADAR,
    focus="project_implementation_radar",
    feature_weights={
        "repo_health": 0.24,
        "activity": 0.20,
        "implementation_evidence": 0.22,
        "community_adoption": 0.18,
        "technology_mapping": 0.16,
    },
    badge_rules=(
        ("healthy repo", "repo_health", 0.65),
        ("active", "activity", 0.55),
        ("implements", "implementation_evidence", 0.45),
        ("mapped tech", "technology_mapping", 0.45),
    ),
    metric_labels={
        "repo_health": "Repo Health",
        "activity": "Activity",
        "implementation_evidence": "Implementation",
        "community_adoption": "Community",
        "technology_mapping": "Tech Mapping",
    },
)


def project_radar_features(card: BoardCard) -> dict[str, float]:
    repo_text = text_signal_score(card, ("github", "repo", "repository", "stars", "forks", "license"))
    return {
        "repo_health": max(repo_text, evidence_strength(card) * 0.8),
        "activity": max(normalized_count(len(card.metrics), 5.0), text_signal_score(card, ("commit", "release", "active", "maintained"))),
        "implementation_evidence": max(relation_strength(card), text_signal_score(card, ("implements", "implementation", "library", "framework"))),
        "community_adoption": max(related_type_strength(card, "community_thread"), text_signal_score(card, ("used", "users", "adoption", "community"))),
        "technology_mapping": related_type_strength(card, "technology"),
    }


def rank_project_card(card: BoardCard):
    features = project_radar_features(card)
    score = sum(features[name] * PROJECT_RADAR_PROFILE.feature_weights[name] for name in PROJECT_RADAR_PROFILE.feature_weights)
    reason = f"Project radar ranking emphasizes repo health/activity/implementation evidence; score={score:.2f}."
    return features, reason, card.score.model_copy(update={"value": min(1.0, round(score, 4))})
