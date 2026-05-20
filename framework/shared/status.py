from __future__ import annotations

from enum import Enum


class RuntimeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    SKIPPED = "skipped"
    DEGRADED = "degraded"

    def is_terminal(self) -> bool:
        return self in {
            RuntimeStatus.SUCCEEDED,
            RuntimeStatus.FAILED,
            RuntimeStatus.CANCELLED,
            RuntimeStatus.SKIPPED,
        }

    def is_success(self) -> bool:
        return self in {RuntimeStatus.SUCCEEDED, RuntimeStatus.SKIPPED}

    def is_failure(self) -> bool:
        return self in {RuntimeStatus.FAILED, RuntimeStatus.CANCELLED}

    @classmethod
    def from_value(cls, value: str | RuntimeStatus) -> RuntimeStatus:
        if isinstance(value, RuntimeStatus):
            return value
        return cls(str(value))
