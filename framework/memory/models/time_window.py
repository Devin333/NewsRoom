from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.shared.time import format_datetime, parse_datetime


@dataclass(frozen=True)
class TimeWindow:
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        start = parse_datetime(self.start)
        end = parse_datetime(self.end)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        if start is not None and end is not None and start > end:
            raise ValueError("time_window start must be before end")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimeWindow":
        return cls(start=payload.get("start"), end=payload.get("end"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": format_datetime(self.start),
            "end": format_datetime(self.end),
        }

    def contains(self, value: datetime) -> bool:
        candidate = parse_datetime(value)
        if candidate is None:
            return False
        if self.start is not None and candidate < self.start:
            return False
        if self.end is not None and candidate > self.end:
            return False
        return True

    def overlaps(self, other: "TimeWindow") -> bool:
        if self.end is not None and other.start is not None and self.end < other.start:
            return False
        if other.end is not None and self.start is not None and other.end < self.start:
            return False
        return True
