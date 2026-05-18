from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from core.framework.workers.models import (
    BackpressurePolicy,
    DeadLetterRecord,
    QueueStatus,
    Task,
    TaskEnqueueResult,
    TaskError,
    TaskEvent,
    TaskRetryPolicy,
    TaskStatus,
    WorkerMetrics,
)


class InMemoryTaskQueue:
    def __init__(
        self,
        *,
        retry_policy: TaskRetryPolicy | None = None,
        backpressure_policy: BackpressurePolicy | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._queued: dict[str, deque[Task]] = {}
        self._in_flight: dict[str, Task] = {}
        self.dead_letters: list[DeadLetterRecord] = []
        self.events: list[TaskEvent] = []
        self.retry_policy = retry_policy or TaskRetryPolicy()
        self.backpressure_policy = backpressure_policy or BackpressurePolicy()
        self.now_fn = now_fn or (lambda: datetime.now(UTC))

    def enqueue(self, task: Task) -> TaskEnqueueResult | None:
        if task.dedup_key and self._has_unfinished_dedup_key(task.dedup_key):
            task.metadata["enqueue_rejected_reason"] = "duplicate_dedup_key"
            return TaskEnqueueResult(
                task_id=task.task_id,
                queue_name=task.queue_name,
                accepted=False,
                status=task.status,
                reason="duplicate_dedup_key",
            )
        pending_count = self.queue_status(task.queue_name).pending_count
        if self.backpressure_policy.should_reject(pending_count=pending_count):
            task.metadata["enqueue_rejected_reason"] = "backpressure"
            return TaskEnqueueResult(
                task_id=task.task_id,
                queue_name=task.queue_name,
                accepted=False,
                status=task.status,
                reason="backpressure",
            )
        task.status = TaskStatus.QUEUED
        task.leased_by = None
        task.lease_expires_at = None
        task.updated_at = self._now()
        self._queued.setdefault(task.queue_name, deque()).append(task)
        self._record_event("task_enqueued", task)
        return None

    def lease(self, worker_id: str, queue_names: list[str]) -> Task | None:
        now = self._now()
        for queue_name in queue_names:
            queue = self._queued.get(queue_name)
            if queue:
                task = self._pop_due_task(queue, now=now)
                if task is None:
                    continue
                task.status = TaskStatus.LEASED
                task.leased_by = worker_id
                task.attempts += 1
                task.metadata["lease_count"] = task.attempts
                if task.timeout_seconds is not None:
                    task.lease_expires_at = now + timedelta(seconds=task.timeout_seconds)
                task.updated_at = now
                self._in_flight[task.task_id] = task
                self._record_event("task_leased", task, worker_id=worker_id)
                return task
        return None

    def ack(self, task_id: str, worker_id: str) -> None:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return
        task.status = TaskStatus.SUCCEEDED
        task.leased_by = None
        task.lease_expires_at = None
        task.updated_at = self._now()
        self._record_event("task_succeeded", task, worker_id=worker_id)

    def fail(self, task_id: str, worker_id: str, error: TaskError) -> None:
        task = self._in_flight.pop(task_id)
        task.metadata["last_error"] = error.to_dict()
        if self.retry_policy.should_retry(task, error):
            next_run_at = self.retry_policy.next_run_at(task, now=self._now())
            task.status = TaskStatus.RETRYING
            task.scheduled_for = next_run_at
            task.leased_by = None
            task.lease_expires_at = None
            task.updated_at = self._now()
            self._record_event(
                "task_retry_scheduled",
                task,
                worker_id=worker_id,
                payload={"next_run_at": next_run_at.isoformat().replace("+00:00", "Z")},
            )
            self.enqueue(task)
            return
        if error.retryable and task.attempts < task.max_attempts:
            task.status = TaskStatus.FAILED
            task.leased_by = None
            task.lease_expires_at = None
            task.updated_at = self._now()
            self._record_event("task_failed", task, worker_id=worker_id, payload=error.to_dict())
            return
        self.move_to_dead_letter(task, error.error_message, error=error)

    def move_to_dead_letter(self, task: Task, reason: str, error: TaskError | None = None) -> None:
        task.status = TaskStatus.DEAD_LETTER
        task.leased_by = None
        task.lease_expires_at = None
        task.updated_at = self._now()
        event = self._record_event(
            "task_dead_lettered",
            task,
            payload={"reason": reason, **(error.to_dict() if error else {})},
        )
        self.dead_letters.append(
            DeadLetterRecord(
                task=task,
                reason=reason,
                error=error,
                attempts=task.attempts,
                failed_at=task.updated_at,
                last_event=event,
            )
        )

    def list_dead_letters(self) -> list[DeadLetterRecord]:
        return list(self.dead_letters)

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
        for index, record in enumerate(list(self.dead_letters)):
            if record.task.task_id != task_id:
                continue
            del self.dead_letters[index]
            task = record.task
            task.metadata["dead_letter_reason"] = record.reason
            task.metadata["requeue_reason"] = reason
            task.status = TaskStatus.QUEUED
            task.leased_by = None
            task.lease_expires_at = None
            task.scheduled_for = None
            task.updated_at = self._now()
            self._queued.setdefault(task.queue_name, deque()).append(task)
            self._record_event("task_requeued", task, payload={"reason": reason})
            return True
        return False

    def reclaim_stale(self, worker_id: str, queue_names: list[str], *, now: datetime | None = None) -> Task | None:
        reference = _coerce_datetime(now) if now else self._now()
        for task_id, task in list(self._in_flight.items()):
            if task.queue_name not in queue_names:
                continue
            if task.lease_expires_at is None or task.lease_expires_at > reference:
                continue
            del self._in_flight[task_id]
            task.status = TaskStatus.LEASED
            previous_worker = task.leased_by
            task.leased_by = worker_id
            task.metadata["reclaimed"] = True
            task.metadata["reclaimed_from_worker"] = previous_worker
            task.metadata["lease_count"] = task.attempts
            task.lease_expires_at = (
                reference + timedelta(seconds=task.timeout_seconds)
                if task.timeout_seconds is not None
                else None
            )
            task.updated_at = reference
            self._in_flight[task.task_id] = task
            self._record_event("task_reclaimed", task, worker_id=worker_id)
            return task
        return None

    def queue_status(self, queue_name: str) -> QueueStatus:
        now = self._now()
        queued = list(self._queued.get(queue_name, ()))
        in_flight = [task for task in self._in_flight.values() if task.queue_name == queue_name]
        delayed = [
            task
            for task in queued
            if task.scheduled_for is not None and _coerce_datetime(task.scheduled_for) > now
        ]
        active_queued = len(queued) - len(delayed)
        oldest = min((task.created_at for task in queued + in_flight), default=None)
        oldest_age = (now - _coerce_datetime(oldest)).total_seconds() if oldest else None
        return QueueStatus(
            queue_name=queue_name,
            pending_count=active_queued + len(in_flight),
            leased_count=len(in_flight),
            delayed_count=len(delayed),
            dead_letter_count=sum(1 for record in self.dead_letters if record.task.queue_name == queue_name),
            lag=active_queued,
            oldest_task_age=oldest_age,
        )

    def metrics(self) -> WorkerMetrics:
        queued_count = sum(len(queue) for queue in self._queued.values())
        dead_letter_count = len(self.dead_letters)
        statuses = [self.queue_status(queue_name) for queue_name in self._all_queue_names()]
        return WorkerMetrics(
            queued_count=queued_count,
            leased_count=len(self._in_flight),
            dead_letter_count=dead_letter_count,
            pending_count=sum(status.pending_count for status in statuses),
            lag=sum(status.lag or 0 for status in statuses),
            oldest_task_age=max(
                (status.oldest_task_age for status in statuses if status.oldest_task_age is not None),
                default=None,
            ),
            cancelled_count=sum(
                1
                for queue in self._queued.values()
                for task in queue
                if task.status == TaskStatus.CANCELLED
            ),
        )

    def _pop_due_task(self, queue: deque[Task], *, now: datetime) -> Task | None:
        for task in list(queue):
            if task.scheduled_for is not None and _coerce_datetime(task.scheduled_for) > now:
                continue
            queue.remove(task)
            return task
        return None

    def _has_unfinished_dedup_key(self, dedup_key: str) -> bool:
        for queue in self._queued.values():
            for task in queue:
                if task.dedup_key == dedup_key and task.status in _UNFINISHED_STATUSES:
                    return True
        return any(
            task.dedup_key == dedup_key and task.status in _UNFINISHED_STATUSES
            for task in self._in_flight.values()
        )

    def _all_queue_names(self) -> list[str]:
        queue_names = set(self._queued)
        queue_names.update(task.queue_name for task in self._in_flight.values())
        queue_names.update(record.task.queue_name for record in self.dead_letters)
        return sorted(queue_names)

    def _record_event(
        self,
        event_type: str,
        task: Task,
        *,
        worker_id: str | None = None,
        payload: dict | None = None,
    ) -> TaskEvent:
        event = TaskEvent(
            event_type=event_type,
            task_id=task.task_id,
            task_status=task.status,
            worker_id=worker_id,
            queue_name=task.queue_name,
            payload=payload or {},
            occurred_at=self._now(),
        )
        self.events.append(event)
        return event

    def _now(self) -> datetime:
        return _coerce_datetime(self.now_fn())


def _cancel_task(task: Task, reason: str | None) -> None:
    task.status = TaskStatus.CANCELLED
    task.leased_by = None
    task.lease_expires_at = None
    task.updated_at = datetime.now(UTC)
    if reason:
        task.metadata["cancel_reason"] = reason


def _coerce_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


_UNFINISHED_STATUSES = {
    TaskStatus.CREATED,
    TaskStatus.QUEUED,
    TaskStatus.LEASED,
    TaskStatus.RUNNING,
    TaskStatus.RETRYING,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.PAUSED,
}
