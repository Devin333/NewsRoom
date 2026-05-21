from business.boards._final_target import ranking_payload
from business.boards.project_radar.policies import project_radar_policy_profile
from business.foundation import BoardCard


def rank_project_card(card: BoardCard):
    return ranking_payload(card, project_radar_policy_profile())
