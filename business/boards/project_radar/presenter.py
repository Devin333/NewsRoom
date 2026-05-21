from business.boards._final_target import present_cards
from business.boards.project_radar.policies import project_radar_policy_profile
from business.foundation import BoardCard


def present_project_cards(cards: list[BoardCard]) -> list[BoardCard]:
    return present_cards(cards, project_radar_policy_profile())
