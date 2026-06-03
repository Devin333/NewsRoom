from __future__ import annotations

from typing import Any

from business.boards.productized.ports import ProductizedSignalSelectionPort
from business.foundation import AnalysisContext


class ProductizedSignalClassificationService:
    def __init__(
        self,
        *,
        selector: ProductizedSignalSelectionPort | None = None,
        board_service: ProductizedSignalSelectionPort | None = None,
    ) -> None:
        resolved_selector = selector or board_service
        if resolved_selector is None:
            raise ValueError("selector or board_service is required")
        self.selector = resolved_selector

    def classify(
        self,
        *,
        context: AnalysisContext,
        prepared_signals: list[Any],
    ) -> dict[str, Any]:
        return {"board_signals": self.selector.select_signals(prepared_signals, context=context)}


__all__ = ["ProductizedSignalClassificationService"]
