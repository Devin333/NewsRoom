from datetime import UTC, datetime

from core.framework.workers import (
    Task,
    TaskEvent,
    TaskRecord,
    TaskRetryPolicy,
    TaskStatus,
    WorkerMetrics,
)
from core.framework.workers.models import TaskError


def test_task_preserves_final_state_fields() -> None:
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        status=TaskStatus.WAITING_FOR_APPROVAL,
        priority=5,
        timeout_seconds=120,
        dedup_key="daily:AI",
        trace_id="trace-1",
        lease_expires_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
    )

    restored = Task.from_dict(task.to_dict())

    assert restored.status == TaskStatus.WAITING_FOR_APPROVAL
    assert restored.priority == 5
    assert restored.timeout_seconds == 120
    assert restored.dedup_key == "daily:AI"
    assert restored.trace_id == "trace-1"
    assert restored.lease_expires_at == datetime(2026, 5, 11, 1, 0, tzinfo=UTC)


def test_retry_policy_respects_retry_budget_and_error_type() -> None:
    task = Task(task_type="daily_intelligence.run", payload={}, attempts=1, max_attempts=3)
    policy = TaskRetryPolicy(max_attempts=3, non_retryable_error_types=["ValidationError"])

    assert policy.should_retry(task, TaskError("Timeout", "timeout")) is True
    assert policy.should_retry(task, TaskError("ValidationError", "bad input")) is False
    assert policy.delay_seconds(2) == 60


def test_task_record_event_and_worker_metrics_to_dict() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    record = TaskRecord.from_task(task, workflow_run_id="run-1")
    event = TaskEvent(event_type="task_queued", task_id=task.task_id, task_status=task.status)
    metrics = WorkerMetrics(queued_count=1, dead_letter_count=2)

    assert record.to_dict()["workflow_run_id"] == "run-1"
    assert event.to_dict()["event_type"] == "task_queued"
    assert metrics.to_dict()["dead_letter_count"] == 2
