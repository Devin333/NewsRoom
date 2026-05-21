from business.boards._intelligence import enhance_board_cards
from business.boards.project_radar.policies import project_radar_policy_profile
from business.boards.project_radar.ranking_rules import PROJECT_RADAR_PROFILE, project_radar_features
from business.foundation import BoardCard


def present_project_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return enhance_board_cards(
        cards,
        profile=PROJECT_RADAR_PROFILE,
        policy=project_radar_policy_profile(),
        feature_builder=project_radar_features,
    )
