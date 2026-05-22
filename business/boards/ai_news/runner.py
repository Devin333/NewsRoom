from __future__ import annotations

from business.boards._runner import ProductizedBoardRunnerBase
from business.boards.ai_news.board_service import AINewsBoardService
from business.foundation import BoardType


class AINewsRunner(ProductizedBoardRunnerBase):
    board_type = BoardType.AI_NEWS
    service_class = AINewsBoardService


__all__ = ["AINewsRunner"]
