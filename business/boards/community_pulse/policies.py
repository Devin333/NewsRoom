from business.boards._final_target import default_board_policy
from business.foundation import BoardType


def community_pulse_policy_profile():
    profile = default_board_policy(BoardType.COMMUNITY_PULSE)
    parameters = {
        **dict(profile.parameters),
        "feature_weights": {
            "discussion_heat": 0.24,
            "sentiment_divergence": 0.20,
            "problem_signal": 0.20,
            "source_diversity": 0.18,
            "freshness": 0.18,
        },
        "minimum_discussion_heat": 0.4,
    }
    return profile.model_copy(update={"parameters": parameters})
