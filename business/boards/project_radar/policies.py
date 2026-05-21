from business.boards._final_target import default_board_policy
from business.foundation import BoardType


def project_radar_policy_profile():
    profile = default_board_policy(BoardType.PROJECT_RADAR)
    parameters = {
        **dict(profile.parameters),
        "feature_weights": {
            "repo_health": 0.24,
            "activity": 0.20,
            "implementation_evidence": 0.22,
            "community_adoption": 0.18,
            "technology_mapping": 0.16,
        },
        "minimum_repo_health": 0.5,
    }
    return profile.model_copy(update={"parameters": parameters})
