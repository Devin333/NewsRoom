from business.boards._final_target import ranking_payload
from business.boards.community_pulse.policies import community_pulse_policy_profile
from business.foundation import BoardCard


def rank_community_card(card: BoardCard):
    return ranking_payload(card, community_pulse_policy_profile())
