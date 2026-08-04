from dataclasses import dataclass

from framework.tool import ToolRegistry, register_control_tools
from framework.tool.builtin import Task as ToolTask
from framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskResult,
    TaskStatus,
    WorkerLoop,
)


@dataclass
class _DelegatedHandler:
    task_type: str = "research.delegate"

    def __post_init__(self) -> None:
        self.seen: list[Task] = []

    def handle(self, task: Task) -> TaskResult:
        self.seen.append(task)
        return TaskResult.success(task.task_id, {"accepted": True})


def test_control_delegation_reaches_worker_through_canonical_task() -> None:
    queue = InMemoryTaskQueue()
    registry = ToolRegistry()
    register_control_tools(registry, task_queue=queue, run_id="run-control")

    delegated = registry.require("control.delegate_to_subagent").executor(
        {
            "task_type": "research.delegate",
            "payload": {"paper_id": "paper-1"},
            "queue_name": "research",
            "max_attempts": 4,
            "subagent_id": "reader",
        }
    )
    handler = _DelegatedHandler()
    result = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handlers={handler.task_type: handler},
        queue_name="research",
        idle_sleep_seconds=0,
    ).run_once()

    assert ToolTask is Task
    assert delegated["message_id"] is None
    assert result is not None and result.success
    assert len(handler.seen) == 1
    task = handler.seen[0]
    assert isinstance(task, Task)
    assert task.task_id == delegated["task_id"]
    assert task.status == TaskStatus.SUCCEEDED
    assert task.payload == {"paper_id": "paper-1"}
    assert task.max_attempts == 4
    assert task.attempts == 1
    assert task.metadata == {
        "control_tool": "control.delegate_to_subagent",
        "run_id": "run-control",
        "subagent_id": "reader",
        "lease_count": 1,
    }
