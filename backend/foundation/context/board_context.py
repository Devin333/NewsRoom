from __future__ import annotations

from pydantic import Field, field_validator

from backend.foundation.context.defaults import default_time_window
from backend.foundation.primitives import PrimitiveModel, TimeWindow
from backend.foundation.taxonomy import BoardType


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


__all__ = ["BoardContext"]
