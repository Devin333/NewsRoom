from business.boards._intelligence import (
    BoardScoringProfile,
    evidence_strength,
    related_type_strength,
    relation_strength,
    text_signal_score,
)
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.foundation import BoardCard, BoardType


PAPER_RADAR_PROFILE = BoardScoringProfile(
    board_type=BoardType.PAPER_RADAR,
    focus="research_method_radar",
    feature_weights={
        "method_novelty": 0.24,
        "evaluation_evidence": 0.22,
        "technology_mapping": 0.20,
        "implementation_potential": 0.18,
        "research_quality": 0.16,
    },
    badge_rules=(
        ("novel method", "method_novelty", 0.45),
        ("benchmark", "evaluation_evidence", 0.45),
        ("mapped tech", "technology_mapping", 0.45),
        ("implementation path", "implementation_potential", 0.45),
    ),
    metric_labels={
        "method_novelty": "Novelty",
        "evaluation_evidence": "Evaluation",
        "technology_mapping": "Tech Mapping",
        "implementation_potential": "Implementation Potential",
        "research_quality": "Research Quality",
    },
)


def paper_radar_features(card: BoardCard) -> dict[str, float]:
    return {
        "method_novelty": text_signal_score(card, ("propose", "novel", "new", "method", "architecture")),
        "evaluation_evidence": text_signal_score(card, ("benchmark", "evaluation", "eval", "sota", "dataset", "ablation")),
        "technology_mapping": related_type_strength(card, "technology"),
        "implementation_potential": max(related_type_strength(card, "project"), relation_strength(card)),
        "research_quality": max(evidence_strength(card), text_signal_score(card, ("arxiv", "paper", "authors", "technical"))),
    }


def rank_paper_card(card: BoardCard):
    policy = paper_radar_policy_profile()
    features = paper_radar_features(card)
    score = sum(features[name] * PAPER_RADAR_PROFILE.feature_weights[name] for name in PAPER_RADAR_PROFILE.feature_weights)
    reason = f"Paper radar ranking emphasizes method novelty/evaluation/implementation path; score={score:.2f}."
    return features, reason, card.score.model_copy(update={"value": min(1.0, round(score, 4))})
