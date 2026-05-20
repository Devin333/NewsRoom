from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkerMetrics:
    queued_count: int = 0
    leased_count: int = 0
    running_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    dead_letter_count: int = 0
    cancelled_count: int = 0
    pending_count: int = 0
    lag: int | None = None
    oldest_task_age: float | None = None
    avg_task_latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_success(self) -> "WorkerMetrics":
        return WorkerMetrics(
            queued_count=self.queued_count,
            leased_count=self.leased_count,
            running_count=self.running_count,
            succeeded_count=self.succeeded_count + 1,
            failed_count=self.failed_count,
            dead_letter_count=self.dead_letter_count,
            cancelled_count=self.cancelled_count,
            pending_count=self.pending_count,
            lag=self.lag,
            oldest_task_age=self.oldest_task_age,
            avg_task_latency_ms=self.avg_task_latency_ms,
            metadata=dict(self.metadata),
        )

    def record_failure(self) -> "WorkerMetrics":
        return WorkerMetrics(
            queued_count=self.queued_count,
            leased_count=self.leased_count,
            running_count=self.running_count,
            succeeded_count=self.succeeded_count,
            failed_count=self.failed_count + 1,
            dead_letter_count=self.dead_letter_count,
            cancelled_count=self.cancelled_count,
            pending_count=self.pending_count,
            lag=self.lag,
            oldest_task_age=self.oldest_task_age,
            avg_task_latency_ms=self.avg_task_latency_ms,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "queued_count": self.queued_count,
            "leased_count": self.leased_count,
            "running_count": self.running_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "dead_letter_count": self.dead_letter_count,
            "cancelled_count": self.cancelled_count,
            "pending_count": self.pending_count,
            "lag": self.lag,
            "oldest_task_age": self.oldest_task_age,
            "avg_task_latency_ms": self.avg_task_latency_ms,
            "metadata": dict(self.metadata),
        }
