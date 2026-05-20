from __future__ import annotations

from dataclasses import dataclass

from framework.workers.models.task import Task
from framework.workers.queue.base import TaskQueue


@dataclass
class LeaseManager:
    queue: TaskQueue
    worker_id: str
    queue_names: list[str]

    def lease_one(self) -> Task | None:
        leased = self.queue.lease(self.worker_id, self.queue_names)
        return leased if isinstance(leased, Task) else None

    def reclaim_stale(self) -> Task | None:
        return self.queue.reclaim_stale(self.worker_id, self.queue_names)
