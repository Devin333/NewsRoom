from __future__ import annotations

from business.boards._runner import ProductizedBoardRunnerBase
from business.boards.community_pulse.board_service import CommunityPulseBoardService
from business.foundation import BoardType


class CommunityPulseRunner(ProductizedBoardRunnerBase):
    board_type = BoardType.COMMUNITY_PULSE
    service_class = CommunityPulseBoardService


__all__ = ["CommunityPulseRunner"]
