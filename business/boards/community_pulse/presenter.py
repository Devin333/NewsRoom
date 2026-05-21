from business.boards._final_target import present_cards
from business.boards.community_pulse.policies import community_pulse_policy_profile
from business.foundation import BoardCard


def present_community_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return present_cards(cards, community_pulse_policy_profile())
