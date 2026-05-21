from __future__ import annotations

from typing import Any

from business.foundation import BoardRunResult, BoardType
from interfaces.services.board_service import BoardApplicationService


class BoardContractService:
    def __init__(self, board_service: BoardApplicationService | None = None) -> None:
        self._board_service = board_service or BoardApplicationService()

    def build_board_dto(self, board_type: BoardType | str, items: list[Any]) -> dict[str, Any]:
        output = self._board_service.build_board_output(board_type, items)
        return output.to_dict()

    def build_board_run_dto(self, board_type: BoardType | str, items: list[Any]) -> dict[str, Any]:
        service = self._board_service._services[BoardType(board_type)]
        result: BoardRunResult = service.build_board_run_result(items)
        return result.to_dict()
