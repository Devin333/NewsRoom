from __future__ import annotations

from datetime import datetime, timezone as _tz

from pydantic import Field, model_validator

from backend.foundation.primitives.base import PrimitiveModel


UTC = _tz.utc


class TimeWindow(PrimitiveModel):
    start: datetime = Field(alias="start_at")
    end: datetime = Field(alias="end_at")
    label: str | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TimeWindow":
        start = ensure_utc(self.start) or self.start
        end = ensure_utc(self.end) or self.end
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if end < start:
            raise ValueError("time window end must be greater than or equal to start")
        return self

    def contains(self, value: datetime) -> bool:
        instant = ensure_utc(value) or value
        return self.start <= instant <= self.end

    @property
    def start_at(self) -> datetime:
        return self.start

    @property
    def end_at(self) -> datetime:
        return self.end


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["TimeWindow", "ensure_utc"]
