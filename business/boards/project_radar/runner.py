from __future__ import annotations

from business.boards._runner import ProductizedBoardRunnerBase
from business.boards.project_radar.board_service import ProjectRadarBoardService
from business.foundation import BoardType


class ProjectRadarRunner(ProductizedBoardRunnerBase):
    board_type = BoardType.PROJECT_RADAR
    service_class = ProjectRadarBoardService


__all__ = ["ProjectRadarRunner"]
