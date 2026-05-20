from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.workers.models.metrics import WorkerMetrics
from framework.workers.queue.base import QueueStatus
from framework.workers.runtime.heartbeat import WorkerHeartbeatStatus


@dataclass(frozen=True)
class WorkerHealth:
    healthy: bool
    queue_status: QueueStatus | None = None
    worker_statuses: tuple[WorkerHeartbeatStatus, ...] = ()
    metrics: WorkerMetrics | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "queue_status": self.queue_status.to_dict() if self.queue_status else None,
            "worker_statuses": [status.to_dict() for status in self.worker_statuses],
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "reason": self.reason,
        }
