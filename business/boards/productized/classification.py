from __future__ import annotations

from typing import Any

from business.boards._service import BoardServiceBase
from business.foundation import AnalysisContext


class ProductizedSignalClassificationService:
    def __init__(self, *, board_service: BoardServiceBase) -> None:
        self.board_service = board_service

    def classify(
        self,
        *,
        context: AnalysisContext,
        prepared_signals: list[Any],
    ) -> dict[str, Any]:
        return {"board_signals": self.board_service.select_signals(prepared_signals, context=context)}


__all__ = ["ProductizedSignalClassificationService"]
