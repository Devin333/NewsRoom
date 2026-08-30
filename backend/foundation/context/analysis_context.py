from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, model_validator

from backend.foundation.context.board_context import BoardContext
from backend.foundation.context.defaults import default_time_window
from backend.foundation.context.run_context import RunContext
from backend.foundation.primitives import PrimitiveModel, TimeWindow, ensure_utc
from backend.foundation.taxonomy import BoardType


UTC = _tz.utc


class AnalysisContext(PrimitiveModel):
    run_context: RunContext | None = None
    board_context: BoardContext | None = None
    time_window: TimeWindow = Field(default_factory=lambda: default_time_window())
    taxonomy_version: str = "v1"
    enable_llm: bool = True
    confidence_threshold: float = 0.5
    board_type: BoardType | None = None
    reference_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def for_board(self, board_type: BoardType) -> "AnalysisContext":
        board_context = BoardContext(
            board_type=board_type,
            source_limit=self.board_context.source_limit if self.board_context else None,
            language=self.board_context.language if self.board_context else "en",
            target_audience=self.board_context.target_audience if self.board_context else "developer",
            time_window=self.board_context.time_window if self.board_context else self.time_window,
        )
        return self.model_copy(update={"board_type": board_type, "board_context": board_context})

    @model_validator(mode="after")
    def _normalize_context(self) -> "AnalysisContext":
        object.__setattr__(self, "reference_time", ensure_utc(self.reference_time) or self.reference_time)
        if self.run_context is not None:
            object.__setattr__(self, "time_window", self.run_context.time_window)
        if self.board_context is not None:
            object.__setattr__(self, "board_type", self.board_context.board_type)
            object.__setattr__(self, "time_window", self.board_context.time_window)
        return self


__all__ = ["AnalysisContext", "default_time_window"]
