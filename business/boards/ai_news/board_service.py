from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.foundation import BoardType


class AINewsBoardService(BoardServiceBase):
    board_type = BoardType.AI_NEWS
