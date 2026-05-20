from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from framework.shared.errors import ValidationError
from framework.shared.time import ensure_utc, utc_now


@dataclass(frozen=True)
class TimeoutPolicy:
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValidationError("timeout_seconds must be positive", code="invalid_timeout")

    def deadline_from(self, start: datetime) -> datetime | None:
        if self.timeout_seconds is None:
            return None
        return ensure_utc(start) + timedelta(seconds=self.timeout_seconds)

    def is_expired(self, start: datetime, now: datetime | None = None) -> bool:
        deadline = self.deadline_from(start)
        if deadline is None:
            return False
        actual_now = ensure_utc(now) if now is not None else utc_now()
        return actual_now >= deadline
