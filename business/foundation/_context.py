from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import Field, field_validator, model_validator

from business.foundation.primitives import PrimitiveModel, TimeWindow, ensure_utc
from business.foundation.taxonomy import BoardType


class RunContext(PrimitiveModel):
    run_id: str
    run_type: str
    time_window: TimeWindow = Field(default_factory=lambda: default_time_window())
    profile: str = "default"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id", "run_type", "profile")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("run context text fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _normalize_created_at(self) -> "RunContext":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at) or self.created_at)
        return self


class BoardContext(PrimitiveModel):
    board_type: BoardType
    source_limit: int | None = None
    language: str = "en"
    target_audience: str = "developer"
    time_window: TimeWindow = Field(default_factory=lambda: default_time_window())

    @field_validator("source_limit")
    @classmethod
    def _validate_source_limit(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("source_limit must be non-negative")
        return value


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


def default_time_window(days: int = 7, *, reference_time: datetime | None = None) -> TimeWindow:
    anchor = ensure_utc(reference_time or datetime.now(UTC)) or datetime.now(UTC)
    return TimeWindow(
        start=anchor - timedelta(days=days),
        end=anchor,
        label=f"last_{days}_days",
    )
