from __future__ import annotations

from dataclasses import dataclass, field

from framework.workers.registry.handler import TaskHandler


@dataclass
class TaskHandlerRegistry:
    handlers: dict[str, TaskHandler] = field(default_factory=dict)

    def register(self, handler: TaskHandler, *, task_type: str | None = None) -> None:
        actual_task_type = task_type or getattr(handler, "task_type", None)
        if not actual_task_type:
            raise ValueError("task_type is required")
        self.handlers[str(actual_task_type)] = handler

    def get(self, task_type: str) -> TaskHandler | None:
        return self.handlers.get(task_type)

    def require(self, task_type: str) -> TaskHandler:
        handler = self.get(task_type)
        if handler is None:
            raise KeyError(task_type)
        return handler

    def to_dict(self) -> dict[str, list[str]]:
        return {"task_types": sorted(self.handlers)}


def registry_from_handlers(handlers: dict[str, TaskHandler] | None = None) -> TaskHandlerRegistry:
    registry = TaskHandlerRegistry()
    for task_type, handler in (handlers or {}).items():
        registry.register(handler, task_type=task_type)
    return registry
