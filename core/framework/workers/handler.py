from __future__ import annotations

from typing import Protocol

from core.framework.workers.models import Task, TaskResult


class TaskHandler(Protocol):
    task_type: str

    def handle(self, task: Task) -> TaskResult:
        ...

