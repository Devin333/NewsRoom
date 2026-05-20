from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.foundation import BoardType


class CrossBoardService(BoardServiceBase):
    board_type = BoardType.CROSS_BOARD
