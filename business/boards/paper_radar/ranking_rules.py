from business.boards._final_target import ranking_payload
from business.boards.paper_radar.policies import paper_radar_policy_profile
from business.foundation import BoardCard


def rank_paper_card(card: BoardCard):
    return ranking_payload(card, paper_radar_policy_profile())
