from __future__ import annotations

from datetime import UTC, datetime

from framework.workers import (
    DeadLetterRecord,
    Task,
    TaskResult,
    TaskRetryPolicy,
    TaskStatus,
    WorkerMetrics,
    WorkerStatus,
)


def test_task_prd_aliases_round_trip() -> None:
    run_at = datetime(2026, 1, 1, tzinfo=UTC)
    task = Task(
        task_type="demo",
        payload={"x": 1},
        queue_name="q",
        scheduled_for=run_at,
        execution_scope="standalone",
    )

    assert task.queue == "q"
    assert task.run_at == run_at
    payload = task.to_dict()
    restored = Task.from_dict({**payload, "queue_name": None})

    assert restored.queue == "q"
    assert restored.run_at == run_at


def test_status_result_retry_metrics_and_dead_letter_helpers() -> None:
    task = Task(task_type="demo", payload={}, execution_scope="standalone")
    assert TaskStatus.SUCCEEDED.is_terminal()
    assert WorkerStatus.IDLE.value == "idle"
    assert TaskRetryPolicy(max_attempts=2).should_retry(1, "temporary")
    assert WorkerMetrics().record_success().succeeded_count == 1
    assert TaskResult.success("task-1", {"ok": True}).status == TaskStatus.SUCCEEDED
    assert TaskResult.failure("task-1", "nope").error_type == "TaskFailed"

    dead_letter = DeadLetterRecord.from_task(task, "failed")
    assert dead_letter.task.status == TaskStatus.DEAD_LETTER
