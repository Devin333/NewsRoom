from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from framework.shared.time import ensure_utc
from framework.workers.models.dead_letter import DeadLetterRecord
from framework.workers.models.metrics import WorkerMetrics
from framework.workers.models.result import TaskEnqueueResult
from framework.workers.models.retry import TaskRetryPolicy
from framework.workers.models.status import TaskStatus
from framework.workers.models.task import DEFAULT_TASK_QUEUE, Task, TaskError, TaskEvent
from framework.workers.queue.base import LeasedTask, QueueStatus
from framework.workers.runtime.backpressure import BackpressurePolicy


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

    def lease(self, *args: Any, **kwargs: Any) -> Task | list[LeasedTask] | None:
        if _is_prd_lease_call(args, kwargs):
            return self._lease_batch(*args, **kwargs)
        worker_id, queue_names = _legacy_lease_args(args, kwargs)
        return self._lease_one(worker_id, queue_names)

    def _lease_batch(self, *args: Any, **kwargs: Any) -> list[LeasedTask]:
        queue_name = kwargs.pop("queue", None)
        worker_id = kwargs.pop("worker_id", None)
        lease_seconds = kwargs.pop("lease_seconds", None)
        limit = kwargs.pop("limit", 1)
        if args:
            queue_name = args[0]
        if len(args) > 1:
            worker_id = args[1]
        if len(args) > 2:
            lease_seconds = args[2]
        if len(args) > 3:
            limit = args[3]
        if kwargs:
            raise TypeError(f"unexpected lease arguments: {sorted(kwargs)}")
        if not queue_name or not worker_id:
            raise TypeError("queue and worker_id are required")
        if lease_seconds is None:
            lease_seconds = 60
        leased: list[LeasedTask] = []
        for _ in range(max(0, int(limit))):
            task = self._lease_one(str(worker_id), [str(queue_name)], lease_seconds=int(lease_seconds))
            if task is None:
                break
            leased.append(LeasedTask(queue_name=task.queue_name, message_id=task.task_id, task=task))
        return leased

    def _lease_one(
        self,
        worker_id: str,
        queue_names: list[str],
        *,
        lease_seconds: int | None = None,
    ) -> Task | None:
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
                actual_lease_seconds = lease_seconds if lease_seconds is not None else task.timeout_seconds
                if actual_lease_seconds is not None:
                    task.lease_expires_at = now + timedelta(seconds=actual_lease_seconds)
                task.updated_at = now
                self._in_flight[task.task_id] = task
                self._record_event("task_leased", task, worker_id=worker_id)
                return task
        return None

    def ack(self, task_id: str, worker_id: str | None = None) -> None:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return
        actual_worker_id = worker_id or task.leased_by
        task.status = TaskStatus.SUCCEEDED
        task.leased_by = None
        task.lease_expires_at = None
        task.updated_at = self._now()
        self._record_event("task_succeeded", task, worker_id=actual_worker_id)

    def nack(self, task_id: str, error: Exception | str, retry_at: datetime | None = None) -> None:
        task = self._in_flight.get(task_id)
        worker_id = task.leased_by if task is not None else None
        task_error = error if isinstance(error, TaskError) else TaskError(type(error).__name__, str(error))
        if retry_at is not None and task is not None:
            task.scheduled_for = ensure_utc(retry_at)
        self.fail(task_id, worker_id or "", task_error)

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
            task.metadata["dead_letter_attempts"] = record.attempts
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

    def reclaim_stale(
        self,
        worker_id: str,
        queue_names: list[str],
        *,
        now: datetime | None = None,
    ) -> Task | None:
        reference = ensure_utc(now) if now else self._now()
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

    def status(self, queue: str | None = None) -> QueueStatus:
        if queue is not None:
            return self.queue_status(queue)
        statuses = [self.queue_status(queue_name) for queue_name in self._all_queue_names()]
        return QueueStatus(
            queue_name="all",
            pending_count=sum(status.pending_count for status in statuses),
            leased_count=sum(status.leased_count for status in statuses),
            delayed_count=sum(status.delayed_count for status in statuses),
            dead_letter_count=sum(status.dead_letter_count for status in statuses),
            lag=sum(status.lag or 0 for status in statuses),
            oldest_task_age=max(
                (status.oldest_task_age for status in statuses if status.oldest_task_age is not None),
                default=None,
            ),
        )

    def queue_status(self, queue_name: str) -> QueueStatus:
        now = self._now()
        queued = list(self._queued.get(queue_name, ()))
        in_flight = [task for task in self._in_flight.values() if task.queue_name == queue_name]
        delayed = [
            task
            for task in queued
            if task.scheduled_for is not None and ensure_utc(task.scheduled_for) > now
        ]
        active_queued = len(queued) - len(delayed)
        oldest = min((task.created_at for task in queued + in_flight), default=None)
        oldest_age = (now - ensure_utc(oldest)).total_seconds() if oldest else None
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
        statuses = [self.queue_status(queue_name) for queue_name in self._all_queue_names()]
        return WorkerMetrics(
            queued_count=queued_count,
            leased_count=len(self._in_flight),
            dead_letter_count=len(self.dead_letters),
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
            if task.scheduled_for is not None and ensure_utc(task.scheduled_for) > now:
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
        if not queue_names:
            queue_names.add(DEFAULT_TASK_QUEUE)
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
        return ensure_utc(self.now_fn())


def _is_prd_lease_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
    if "queue" in kwargs or "lease_seconds" in kwargs or "limit" in kwargs:
        return True
    return len(args) >= 3


def _legacy_lease_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, list[str]]:
    if kwargs:
        worker_id = kwargs.get("worker_id")
        queue_names = kwargs.get("queue_names")
    else:
        worker_id = args[0] if len(args) > 0 else None
        queue_names = args[1] if len(args) > 1 else None
    if not worker_id or queue_names is None:
        raise TypeError("worker_id and queue_names are required")
    return str(worker_id), [str(queue_name) for queue_name in queue_names]


def _cancel_task(task: Task, reason: str | None) -> None:
    task.status = TaskStatus.CANCELLED
    task.leased_by = None
    task.lease_expires_at = None
    task.updated_at = datetime.now(UTC)
    if reason:
        task.metadata["cancel_reason"] = reason


_UNFINISHED_STATUSES = {
    TaskStatus.PENDING,
    TaskStatus.CREATED,
    TaskStatus.QUEUED,
    TaskStatus.LEASED,
    TaskStatus.RUNNING,
    TaskStatus.RETRYING,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.PAUSED,
}
