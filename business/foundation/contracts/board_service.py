from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from business.foundation.context import AnalysisContext
from business.foundation.models import Signal
from business.foundation.taxonomy import BoardType


@runtime_checkable
class BoardService(Protocol):
    board_type: BoardType

    def build_board_output(self, signals: list[Signal], *, context: AnalysisContext | None = None) -> Any: ...


__all__ = ["BoardService"]
