from __future__ import annotations

from pydantic import model_validator

from backend.foundation.primitives.base import PrimitiveModel


class TextSpan(PrimitiveModel):
    start: int
    end: int
    text: str | None = None
    source_text: str | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TextSpan":
        if self.start < 0:
            raise ValueError("text span start must be non-negative")
        if self.end < self.start:
            raise ValueError("text span end must be greater than or equal to start")
        return self


__all__ = ["TextSpan"]
