from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class WorkerExecutionPolicy:
    """Typed attempt and deadline limits for one leased worker task."""

    max_total_retries: int = 0
    min_start_window_seconds: float = 0.0
    cancellation_grace_seconds: float = 0.1
    completion_reserve_seconds: float = 0.0
    verify_reserve_seconds: float = 0.0
    commit_reserve_seconds: float = 0.0

    def __post_init__(self) -> None:
        if type(self.max_total_retries) is not int or self.max_total_retries < 0:
            raise ValueError("max_total_retries must be a non-negative integer")
        for field_name in (
            "min_start_window_seconds",
            "cancellation_grace_seconds",
            "completion_reserve_seconds",
            "verify_reserve_seconds",
            "commit_reserve_seconds",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{field_name} must be finite and non-negative")

    def validate_timeout(self, timeout_seconds: float | None) -> None:
        if timeout_seconds is None:
            return
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) <= 0
        ):
            raise ValueError("worker timeout_seconds must be finite and positive")
        required = (
            self.min_start_window_seconds
            + self.cancellation_grace_seconds
            + self.completion_reserve_seconds
            + self.verify_reserve_seconds
            + self.commit_reserve_seconds
        )
        if required > float(timeout_seconds):
            raise ValueError(
                "worker deadline reserves and minimum start window exceed "
                "timeout_seconds"
            )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_total_retries": self.max_total_retries,
            "min_start_window_seconds": self.min_start_window_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "completion_reserve_seconds": self.completion_reserve_seconds,
            "verify_reserve_seconds": self.verify_reserve_seconds,
            "commit_reserve_seconds": self.commit_reserve_seconds,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "WorkerExecutionPolicy":
        payload = dict(value or {})
        if "max_total_attempts" in payload:
            raise ValueError(
                "legacy max_total_attempts requires explicit migration to "
                "max_total_retries"
            )
        supported = cls().to_dict().keys()
        return cls(**{key: payload[key] for key in supported if key in payload})
