from __future__ import annotations

from typing import Protocol

from framework.workers.models.result import TaskResult
from framework.workers.models.task import Task


class TaskHandler(Protocol):
    task_type: str

    def handle(self, task: Task) -> TaskResult:
        ...
