from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.foundation.context import AnalysisContext
from backend.foundation.models import Signal
from backend.foundation.taxonomy import BoardType


@runtime_checkable
class BoardService(Protocol):
    board_type: BoardType

    def build_board_output(self, signals: list[Signal], *, context: AnalysisContext | None = None) -> Any: ...


__all__ = ["BoardService"]
