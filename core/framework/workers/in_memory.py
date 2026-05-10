from __future__ import annotations

from collections import deque

from core.framework.workers.models import Task, TaskError, TaskStatus


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
            self.enqueue(task)

    def move_to_dead_letter(self, task: Task, reason: str) -> None:
        task.status = TaskStatus.DEAD_LETTER
        self.dead_letters.append((task, reason))
