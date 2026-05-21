from business.boards._intelligence import enhance_board_cards
from business.boards.community_pulse.policies import community_pulse_policy_profile
from business.boards.community_pulse.ranking_rules import COMMUNITY_PULSE_PROFILE, community_pulse_features
from business.foundation import BoardCard


def present_community_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return enhance_board_cards(
        cards,
        profile=COMMUNITY_PULSE_PROFILE,
        policy=community_pulse_policy_profile(),
        feature_builder=community_pulse_features,
    )
