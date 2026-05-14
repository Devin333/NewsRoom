from datetime import UTC, datetime

from core.framework.workers import (
    BackpressurePolicy,
    DeadLetterRecord,
    QueueStatus,
    Task,
    TaskEnqueueResult,
    TaskEvent,
    TaskRecord,
    TaskRetryPolicy,
    TaskResult,
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
        attempts=2,
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
    assert restored.attempt == 2
    restored.attempt = 3
    assert restored.attempts == 3
    assert restored.to_dict()["attempt"] == 3
    assert "quality_gate_blocked" not in {status.value for status in TaskStatus}


def test_retry_policy_respects_retry_budget_and_error_type() -> None:
    task = Task(task_type="daily_intelligence.run", payload={}, attempts=1, max_attempts=3)
    policy = TaskRetryPolicy(max_attempts=3, non_retryable_error_types=["ValidationError"])

    assert policy.should_retry(task, TaskError("Timeout", "timeout")) is True
    assert policy.should_retry(task, TaskError("ValidationError", "bad input")) is False
    assert policy.delay_seconds(2) == 60
    assert policy.next_run_at(task, now=datetime(2026, 5, 11, 0, 0, tzinfo=UTC)) == datetime(
        2026,
        5,
        11,
        0,
        0,
        30,
        tzinfo=UTC,
    )


def test_task_record_event_and_worker_metrics_to_dict() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    record = TaskRecord.from_task(task, workflow_run_id="run-1")
    event = TaskEvent(event_type="task_queued", task_id=task.task_id, task_status=task.status)
    metrics = WorkerMetrics(queued_count=1, dead_letter_count=2)

    assert record.to_dict()["workflow_run_id"] == "run-1"
    assert event.to_dict()["event_type"] == "task_queued"
    assert metrics.to_dict()["dead_letter_count"] == 2


def test_task_result_separates_task_run_and_report_status() -> None:
    result = TaskResult(
        task_id="task-1",
        success=True,
        status=TaskStatus.SUCCEEDED,
        workflow_run_id="run-1",
        run_status="blocked",
        report_status="blocked",
    )

    payload = result.to_dict()

    assert payload["status"] == "succeeded"
    assert payload["task_status"] == "succeeded"
    assert payload["run_status"] == "blocked"
    assert payload["report_status"] == "blocked"


def test_dead_letter_enqueue_and_queue_status_payloads_are_json_safe() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    error = TaskError("TaskFailed", "failed")
    event = TaskEvent("task_dead_lettered", task_id=task.task_id, task_status=TaskStatus.DEAD_LETTER)
    dead_letter = DeadLetterRecord(task=task, reason="failed", error=error, attempts=2, last_event=event)
    enqueue = TaskEnqueueResult(
        task_id=task.task_id,
        queue_name=task.queue_name,
        accepted=False,
        status=TaskStatus.CREATED,
        reason="backpressure",
    )
    status = QueueStatus(queue_name=task.queue_name, pending_count=4, lag=3, oldest_task_age=12.5)

    assert dead_letter.to_dict()["attempts"] == 2
    assert dead_letter.to_dict()["last_event"]["event_type"] == "task_dead_lettered"
    assert enqueue.to_dict()["accepted"] is False
    assert enqueue.to_dict()["reason"] == "backpressure"
    assert status.to_dict()["pending_count"] == 4
    assert BackpressurePolicy(max_pending_per_queue=4).should_reject(pending_count=4) is True
