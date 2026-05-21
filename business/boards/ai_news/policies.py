from business.boards._final_target import default_board_policy
from business.foundation import BoardType


def ai_news_policy_profile():
    profile = default_board_policy(BoardType.AI_NEWS)
    parameters = {
        **dict(profile.parameters),
        "feature_weights": {
            "release_signal": 0.22,
            "adoption_signal": 0.24,
            "vendor_authority": 0.18,
            "impact_surface": 0.18,
            "evidence_strength": 0.18,
        },
        "minimum_vendor_authority": 0.45,
    }
    return profile.model_copy(update={"parameters": parameters})
