from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class ExecutionPolicy:
    enabled: bool = True
    disabled_reason: str | None = None
    max_total_retries: int = 0
    cancellation_grace_seconds: float = 0.1
    verify_reserve_seconds: float = 0.0
    commit_reserve_seconds: float = 0.0

    def __post_init__(self) -> None:
        if type(self.max_total_retries) is not int or self.max_total_retries < 0:
            raise ValueError("max_total_retries must be a non-negative integer")
        for name in (
            "cancellation_grace_seconds",
            "verify_reserve_seconds",
            "commit_reserve_seconds",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")

    def can_execute(self, context: Any) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, self.disabled_reason or "execution disabled"
        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "max_total_retries": self.max_total_retries,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "verify_reserve_seconds": self.verify_reserve_seconds,
            "commit_reserve_seconds": self.commit_reserve_seconds,
        }
