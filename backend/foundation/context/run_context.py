from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from pydantic import Field, field_validator, model_validator

from backend.foundation.context.defaults import default_time_window
from backend.foundation.primitives import PrimitiveModel, TimeWindow, ensure_utc


UTC = _tz.utc


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


__all__ = ["RunContext"]
