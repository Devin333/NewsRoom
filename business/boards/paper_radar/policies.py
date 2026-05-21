from business.boards._final_target import default_board_policy
from business.foundation import BoardType


def paper_radar_policy_profile():
    profile = default_board_policy(BoardType.PAPER_RADAR)
    parameters = {
        **dict(profile.parameters),
        "feature_weights": {
            "method_novelty": 0.24,
            "evaluation_evidence": 0.22,
            "technology_mapping": 0.20,
            "implementation_potential": 0.18,
            "research_quality": 0.16,
        },
        "minimum_evaluation_evidence": 0.35,
    }
    return profile.model_copy(update={"parameters": parameters})
