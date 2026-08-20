from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.shared.graph_identity import GraphExecutionIdentity
from framework.workers import (
    InMemoryTaskQueue,
    Task,
    TaskHandlerRegistry,
    TaskResult,
    TaskStatus,
    WorkerLoop,
)


CHECKSUM = "sha256:" + "b" * 64


def _identity(*, node_instance_id: str = "node:1", attempt: int = 1) -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id="run-worker",
        graph_id="research.worker",
        graph_version="1",
        graph_ref="research.worker@1",
        graph_checksum=CHECKSUM,
        node_id="worker",
        node_instance_id=node_instance_id,
        activity_id="activity-worker",
        attempt=attempt,
    )


@dataclass
class _MatchingHandler:
    task_type: str = "graph.demo"

    def handle(self, task: Task) -> TaskResult:
        return TaskResult.success(
            task.task_id,
            {"ok": True},
            graph_identity=task.graph_identity,
        )


@dataclass
class _MismatchingHandler:
    task_type: str = "graph.demo"

    def handle(self, task: Task) -> TaskResult:
        return TaskResult.success(
            task.task_id,
            {"ok": True},
            graph_identity=_identity(node_instance_id="other:1"),
        )


def test_worker_loop_preserves_exact_execution_identity_on_success() -> None:
    identity = _identity()
    task = Task(
        task_type="graph.demo",
        payload={"value": 1},
        queue_name="q",
        graph_identity=identity,
    )
    queue = InMemoryTaskQueue()
    queue.enqueue(task)
    registry = TaskHandlerRegistry()
    registry.register(_MatchingHandler())

    result = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handler_registry=registry,
        queue_name="q",
        idle_sleep_seconds=0,
    ).run_once()

    assert result is not None
    assert result.success is True
    assert result.graph_identity == identity


def test_worker_loop_rejects_handler_result_identity_mismatch() -> None:
    identity = _identity()
    task = Task(
        task_type="graph.demo",
        payload={},
        queue_name="q",
        graph_identity=identity,
    )
    queue = InMemoryTaskQueue()
    queue.enqueue(task)
    registry = TaskHandlerRegistry()
    registry.register(_MismatchingHandler())

    result = WorkerLoop(
        worker_id="worker-1",
        queue=queue,
        handler_registry=registry,
        queue_name="q",
        idle_sleep_seconds=0,
    ).run_once()

    assert result is not None
    assert result.success is False
    assert result.status is TaskStatus.FAILED
    assert result.error_type == "GraphIdentityMismatch"
    assert result.graph_identity == identity


def test_task_round_trip_preserves_execution_identity_variant() -> None:
    identity = _identity(attempt=2)
    task = Task(task_type="graph.demo", payload={}, graph_identity=identity)

    restored = Task.from_dict(task.to_dict())

    assert restored.graph_identity == identity
    assert restored.graph_identity.attempt == 2  # type: ignore[union-attr]


def test_task_rejects_unknown_mixed_identity_fields() -> None:
    with pytest.raises(ValueError):
        Task.from_dict(
            {
                "task_type": "graph.demo",
                "payload": {},
                "graph_identity": {
                    **_identity().to_dict(),
                    "workflow_id": "legacy",
                },
            }
        )
