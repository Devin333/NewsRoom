from business.boards._final_target import default_board_policy
from business.foundation import BoardType


def cross_board_policy_profile():
    return default_board_policy(BoardType.CROSS_BOARD)
