from __future__ import annotations

from dataclasses import dataclass

from framework.workers.diagnostics.health import WorkerHealth
from framework.workers.models.metrics import WorkerMetrics
from framework.workers.queue.in_memory import InMemoryTaskQueue


@dataclass
class WorkerInspector:
    queue: InMemoryTaskQueue

    def health(self) -> WorkerHealth:
        return WorkerHealth(
            healthy=True,
            queue_status=self.queue.status(),
            metrics=self.queue.metrics(),
        )

    def metrics(self) -> WorkerMetrics:
        return self.queue.metrics()
