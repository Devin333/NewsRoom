from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.foundation import BoardType


class CommunityPulseBoardService(BoardServiceBase):
    board_type = BoardType.COMMUNITY_PULSE
