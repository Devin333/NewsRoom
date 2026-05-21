from business.boards._final_target import present_cards
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.foundation import BoardCard


def present_paper_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return present_cards(cards, paper_radar_policy_profile())
