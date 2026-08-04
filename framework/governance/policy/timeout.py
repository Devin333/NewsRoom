from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from framework.shared.errors import ValidationError
from framework.shared.time import ensure_utc, utc_now


@dataclass(frozen=True)
class TimeoutPolicy:
    timeout_seconds: float | None = None
    min_start_window_seconds: float = 0.0
    cancellation_grace_seconds: float = 0.1
    completion_reserve_seconds: float = 0.0

    def __post_init__(self) -> None:
        values = {
            "min_start_window_seconds": self.min_start_window_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "completion_reserve_seconds": self.completion_reserve_seconds,
        }
        if self.timeout_seconds is not None:
            values["timeout_seconds"] = self.timeout_seconds
        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValidationError(
                    f"{name} must be finite and non-negative",
                    code="invalid_timeout",
                )
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValidationError("timeout_seconds must be positive", code="invalid_timeout")
        if (
            self.timeout_seconds is not None
            and self.min_start_window_seconds > self.timeout_seconds
        ):
            raise ValidationError(
                "min_start_window_seconds must not exceed timeout_seconds",
                code="invalid_timeout",
            )

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
