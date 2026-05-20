from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.foundation import BoardType


class PaperRadarBoardService(BoardServiceBase):
    board_type = BoardType.PAPER_RADAR
