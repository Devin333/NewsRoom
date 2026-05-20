from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.foundation import BoardType


class ProjectRadarBoardService(BoardServiceBase):
    board_type = BoardType.PROJECT_RADAR
