from __future__ import annotations

from business.boards._runner import ProductizedBoardRunnerBase
from business.boards.paper_radar.board_service import PaperRadarBoardService
from business.foundation import BoardType


class PaperRadarRunner(ProductizedBoardRunnerBase):
    board_type = BoardType.PAPER_RADAR
    service_class = PaperRadarBoardService


__all__ = ["PaperRadarRunner"]
