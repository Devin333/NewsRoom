from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta

from core.framework.workers.models import Task, TaskError, TaskStatus, WorkerMetrics


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._queued: dict[str, deque[Task]] = {}
        self._in_flight: dict[str, Task] = {}
        self.dead_letters: list[tuple[Task, str]] = []

    def enqueue(self, task: Task) -> None:
        task.status = TaskStatus.QUEUED
        task.leased_by = None
        self._queued.setdefault(task.queue_name, deque()).append(task)

    def lease(self, worker_id: str, queue_names: list[str]) -> Task | None:
        for queue_name in queue_names:
            queue = self._queued.get(queue_name)
            if queue:
                task = queue.popleft()
                task.status = TaskStatus.LEASED
                task.leased_by = worker_id
                task.attempts += 1
                if task.timeout_seconds is not None:
                    task.lease_expires_at = datetime.now(UTC) + timedelta(seconds=task.timeout_seconds)
                task.updated_at = datetime.now(UTC)
                self._in_flight[task.task_id] = task
                return task
        return None

    def ack(self, task_id: str, worker_id: str) -> None:
        self._in_flight.pop(task_id, None)

    def fail(self, task_id: str, worker_id: str, error: TaskError) -> None:
        task = self._in_flight.pop(task_id)
        task.status = TaskStatus.FAILED
        if task.attempts >= task.max_attempts:
            self.move_to_dead_letter(task, error.error_message)
        else:
            task.status = TaskStatus.RETRYING
            task.metadata["last_error"] = error.to_dict()
            self.enqueue(task)

    def move_to_dead_letter(self, task: Task, reason: str) -> None:
        task.status = TaskStatus.DEAD_LETTER
        task.updated_at = datetime.now(UTC)
        self.dead_letters.append((task, reason))

    def cancel(self, task_id: str, *, reason: str | None = None) -> bool:
        for queue in self._queued.values():
            for task in list(queue):
                if task.task_id != task_id:
                    continue
                queue.remove(task)
                _cancel_task(task, reason)
                return True
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return False
        _cancel_task(task, reason)
        return True

    def requeue_dead_letter(self, task_id: str, *, reason: str = "manual_requeue") -> bool:
        for index, (task, dead_letter_reason) in enumerate(list(self.dead_letters)):
            if task.task_id != task_id:
                continue
            del self.dead_letters[index]
            task.metadata["dead_letter_reason"] = dead_letter_reason
            task.metadata["requeue_reason"] = reason
            task.status = TaskStatus.QUEUED
            task.leased_by = None
            task.lease_expires_at = None
            task.updated_at = datetime.now(UTC)
            self._queued.setdefault(task.queue_name, deque()).append(task)
            return True
        return False

    def metrics(self) -> WorkerMetrics:
        queued_count = sum(len(queue) for queue in self._queued.values())
        dead_letter_count = len(self.dead_letters)
        return WorkerMetrics(
            queued_count=queued_count,
            leased_count=len(self._in_flight),
            dead_letter_count=dead_letter_count,
            cancelled_count=sum(
                1
                for queue in self._queued.values()
                for task in queue
                if task.status == TaskStatus.CANCELLED
            ),
        )


def _cancel_task(task: Task, reason: str | None) -> None:
    task.status = TaskStatus.CANCELLED
    task.leased_by = None
    task.lease_expires_at = None
    task.updated_at = datetime.now(UTC)
    if reason:
        task.metadata["cancel_reason"] = reason
