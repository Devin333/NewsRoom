from business.boards._intelligence import enhance_board_cards
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.boards.paper_radar.ranking_rules import PAPER_RADAR_PROFILE, paper_radar_features
from business.foundation import BoardCard


def present_paper_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return enhance_board_cards(
        cards,
        profile=PAPER_RADAR_PROFILE,
        policy=paper_radar_policy_profile(),
        feature_builder=paper_radar_features,
    )
