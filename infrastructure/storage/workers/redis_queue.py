from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.workers.models import (
    DEFAULT_TASK_QUEUE,
    DeadLetterRecord,
    LeasedTask,
    Task,
    TaskEnqueueResult,
    TaskError,
    TaskEvent,
    TaskRetryPolicy,
    TaskStatus,
)
from framework.workers.runtime.heartbeat import WorkerHeartbeat, WorkerHeartbeatStatus


@dataclass(frozen=True)
class RedisQueueConsumerStatus:
    consumer_name: str
    pending_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumer_name": self.consumer_name,
            "pending_count": self.pending_count,
        }


@dataclass(frozen=True)
class RedisQueueStatus:
    queue_name: str
    stream_length: int
    group_name: str
    group_exists: bool
    pending_count: int = 0
    lag: int | None = None
    entries_read: int | None = None
    last_delivered_id: str | None = None
    oldest_task_age: float | None = None
    consumers: list[RedisQueueConsumerStatus] | None = None

    def to_dict(self) -> dict[str, Any]:
        consumers = self.consumers or []
        return {
            "queue_name": self.queue_name,
            "stream_length": self.stream_length,
            "group_name": self.group_name,
            "group_exists": self.group_exists,
            "pending_count": self.pending_count,
            "lag": self.stream_length if self.lag is None else self.lag,
            "entries_read": self.entries_read,
            "last_delivered_id": self.last_delivered_id,
            "oldest_task_age": self.oldest_task_age,
            "consumer_count": len(consumers),
            "consumers": [consumer.to_dict() for consumer in consumers],
        }


class RedisStreamTaskQueue:
    def __init__(
        self,
        redis_client: Any,
        *,
        group_name: str = "framework-workers",
        dead_letter_queue_name: str = f"{DEFAULT_TASK_QUEUE}:dead-letter",
        retry_policy: TaskRetryPolicy | None = None,
    ) -> None:
        self.redis = redis_client
        self.group_name = group_name
        self.dead_letter_queue_name = dead_letter_queue_name
        self.retry_policy = retry_policy or TaskRetryPolicy()

    def enqueue(self, task: Task) -> str:
        task.status = TaskStatus.QUEUED
        task.leased_by = None
        task.lease_expires_at = None
        task.updated_at = datetime.now(UTC)
        return self.redis.xadd(
            task.queue_name,
            {"task": json.dumps(_redacted_task_dict(task), ensure_ascii=False, sort_keys=True)},
        )

    def ensure_group(self, queue_names: list[str]) -> None:
        for queue_name in queue_names:
            try:
                self.redis.xgroup_create(queue_name, self.group_name, id="0-0", mkstream=True)
            except Exception as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    def lease(self, worker_id: str, queue_names: list[str], *, count: int = 1, block_ms: int = 1000):
        streams = {queue_name: ">" for queue_name in queue_names}
        return self.redis.xreadgroup(self.group_name, worker_id, streams, count=count, block=block_ms)

    def lease_one(
        self,
        worker_id: str,
        queue_names: list[str],
        *,
        block_ms: int = 1000,
    ) -> LeasedTask | None:
        self.ensure_group(queue_names)
        records = self.lease(worker_id, queue_names, count=1, block_ms=block_ms)
        for queue_name, messages in records or []:
            decoded_queue_name = _decode(queue_name)
            for message_id, fields in messages:
                return _leased_task_from_message(
                    queue_name=decoded_queue_name,
                    message_id=message_id,
                    fields=fields,
                    worker_id=worker_id,
                )
        return None

    def reclaim_stale_one(
        self,
        worker_id: str,
        queue_names: list[str],
        *,
        min_idle_ms: int,
        pending_count: int = 10,
    ) -> LeasedTask | None:
        if min_idle_ms < 0:
            raise ValueError("min_idle_ms must be non-negative")
        self.ensure_group(queue_names)
        for queue_name in queue_names:
            pending_entries = self.redis.xpending_range(
                queue_name,
                self.group_name,
                min="-",
                max="+",
                count=pending_count,
            )
            stale_ids = [
                _pending_message_id(entry)
                for entry in pending_entries or []
                if _pending_idle_ms(entry) >= min_idle_ms
            ]
            if not stale_ids:
                continue
            messages = self.redis.xclaim(
                queue_name,
                self.group_name,
                worker_id,
                min_idle_ms,
                stale_ids[:1],
            )
            for message_id, fields in messages or []:
                return _leased_task_from_message(
                    queue_name=queue_name,
                    message_id=message_id,
                    fields=fields,
                    worker_id=worker_id,
                    reclaimed=True,
                )
        return None

    def ack(self, queue_name: str, message_id: str) -> int:
        return self.redis.xack(queue_name, self.group_name, message_id)

    def fail(self, leased: LeasedTask, error: TaskError) -> TaskEnqueueResult:
        task = leased.task
        task.metadata["last_error"] = error.to_dict()
        if self.retry_policy.should_retry(task, error):
            next_run_at = self.retry_policy.next_run_at(task)
            task.status = TaskStatus.RETRYING
            task.scheduled_for = next_run_at
            task.metadata["retry_next_run_at"] = next_run_at.isoformat().replace("+00:00", "Z")
            message_id = self.enqueue(task)
            self.ack(leased.queue_name, leased.message_id)
            return TaskEnqueueResult(
                task_id=task.task_id,
                queue_name=task.queue_name,
                accepted=True,
                status=TaskStatus.RETRYING,
                message_id=str(message_id),
                delayed_until=next_run_at,
            )
        message_id = self.move_to_dead_letter(task, error.error_message, error=error)
        self.ack(leased.queue_name, leased.message_id)
        return TaskEnqueueResult(
            task_id=task.task_id,
            queue_name=self.dead_letter_queue_name,
            accepted=True,
            status=TaskStatus.DEAD_LETTER,
            message_id=str(message_id),
            reason=error.error_message,
        )

    def move_to_dead_letter(self, task: Task, reason: str, error: TaskError | None = None) -> str:
        task.status = TaskStatus.DEAD_LETTER
        task.updated_at = datetime.now(UTC)
        payload = _redacted_task_dict(task)
        payload["dead_letter_reason"] = reason
        if error is not None:
            payload["dead_letter_error"] = error.to_dict()
        payload["dead_letter_failed_at"] = task.updated_at.isoformat().replace("+00:00", "Z")
        payload["dead_letter_last_event"] = TaskEvent(
            event_type="task_dead_lettered",
            task_id=task.task_id,
            task_status=TaskStatus.DEAD_LETTER,
            queue_name=task.queue_name,
            payload={"reason": reason, **(error.to_dict() if error else {})},
            occurred_at=task.updated_at,
        ).to_dict()
        return self.redis.xadd(
            self.dead_letter_queue_name,
            {"task": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
        )

    def list_dead_letters(self, *, count: int = 100) -> list[DeadLetterRecord]:
        records = self.redis.xrange(self.dead_letter_queue_name, min="-", max="+", count=count)
        dead_letters: list[DeadLetterRecord] = []
        for _message_id, fields in records or []:
            payload = json.loads(_decode(_field_value(fields, "task")))
            task = Task.from_dict(payload)
            error_payload = payload.get("dead_letter_error")
            last_event_payload = payload.get("dead_letter_last_event")
            dead_letters.append(
                DeadLetterRecord(
                    task=task,
                    reason=str(payload.get("dead_letter_reason") or "dead_lettered"),
                    error=TaskError(**error_payload) if error_payload else None,
                    attempts=int(payload.get("attempts") or task.attempts),
                    failed_at=_parse_datetime(payload.get("dead_letter_failed_at")),
                    last_event=TaskEvent(**last_event_payload) if last_event_payload else None,
                )
            )
        return dead_letters

    def requeue_dead_letter(self, task_id: str, *, reason: str = "manual_requeue") -> bool:
        records = self.redis.xrange(self.dead_letter_queue_name, min="-", max="+", count=1000)
        for message_id, fields in records or []:
            payload = json.loads(_decode(_field_value(fields, "task")))
            if str(payload.get("task_id")) != task_id:
                continue
            task = Task.from_dict(payload)
            task.metadata["dead_letter_reason"] = payload.get("dead_letter_reason")
            task.metadata["dead_letter_attempts"] = int(payload.get("attempts") or task.attempts)
            task.metadata["requeue_reason"] = reason
            task.status = TaskStatus.QUEUED
            task.scheduled_for = None
            self.enqueue(task)
            if hasattr(self.redis, "xdel"):
                self.redis.xdel(self.dead_letter_queue_name, _decode(message_id))
            return True
        return False

    def status(self, queue_names: list[str]) -> list[RedisQueueStatus]:
        return [self._queue_status(queue_name) for queue_name in queue_names]

    def _queue_status(self, queue_name: str) -> RedisQueueStatus:
        stream_length = int(self.redis.xlen(queue_name) or 0)
        try:
            pending = self.redis.xpending(queue_name, self.group_name)
        except Exception as exc:
            if "NOGROUP" not in str(exc):
                raise
            return RedisQueueStatus(
                queue_name=queue_name,
                stream_length=stream_length,
                group_name=self.group_name,
                group_exists=False,
                lag=stream_length,
            )

        consumers = [
            RedisQueueConsumerStatus(
                consumer_name=str(_decode(_dict_value(consumer, "name"))),
                pending_count=int(_dict_value(consumer, "pending") or 0),
            )
            for consumer in _dict_value(pending, "consumers") or []
        ]
        group_info = self._queue_group_info(queue_name)
        lag = _non_negative_int(_dict_value(group_info, "lag"))
        if lag is None:
            lag = stream_length
        return RedisQueueStatus(
            queue_name=queue_name,
            stream_length=stream_length,
            group_name=self.group_name,
            group_exists=True,
            pending_count=int(_dict_value(pending, "pending") or 0),
            lag=lag,
            entries_read=_non_negative_int(_dict_value(group_info, "entries-read")),
            last_delivered_id=_optional_decoded_text(_dict_value(group_info, "last-delivered-id")),
            consumers=consumers,
        )

    def _queue_group_info(self, queue_name: str) -> dict[Any, Any]:
        if not hasattr(self.redis, "xinfo_groups"):
            return {}
        try:
            groups = self.redis.xinfo_groups(queue_name)
        except Exception:
            return {}
        for group in groups or []:
            if str(_decode(_dict_value(group, "name")) or "") == self.group_name:
                return dict(group)
        return {}


class RedisWorkerRegistry:
    def __init__(self, redis_client: Any, *, key_prefix: str = "news:workers") -> None:
        self.redis = redis_client
        self.key_prefix = key_prefix.rstrip(":")
        self.index_key = f"{self.key_prefix}:index"

    def save(self, record: WorkerHeartbeat) -> WorkerHeartbeat:
        self.redis.set(
            self._worker_key(record.worker_id),
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True),
        )
        self.redis.sadd(self.index_key, record.worker_id)
        return record

    def heartbeat(self, record: WorkerHeartbeat) -> WorkerHeartbeat:
        return self.save(record)

    def get(self, worker_id: str) -> WorkerHeartbeat | None:
        raw = self.redis.get(self._worker_key(worker_id))
        if raw is None:
            return None
        return WorkerHeartbeat.from_dict(json.loads(_decode(raw)))

    def list(self) -> list[WorkerHeartbeat]:
        worker_ids = sorted(str(_decode(worker_id)) for worker_id in self.redis.smembers(self.index_key))
        records: list[WorkerHeartbeat] = []
        for worker_id in worker_ids:
            record = self.get(worker_id)
            if record is None:
                self.redis.srem(self.index_key, worker_id)
                continue
            records.append(record)
        return records

    def status(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 60,
    ) -> WorkerHeartbeatStatus | None:
        record = self.get(worker_id)
        if record is None:
            return None
        return WorkerHeartbeatStatus.from_record(
            record,
            now=now,
            stale_after_seconds=stale_after_seconds,
        )

    def list_statuses(
        self,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 60,
    ) -> list[WorkerHeartbeatStatus]:
        return [
            WorkerHeartbeatStatus.from_record(
                record,
                now=now,
                stale_after_seconds=stale_after_seconds,
            )
            for record in self.list()
        ]

    def delete(self, worker_id: str) -> None:
        self.redis.delete(self._worker_key(worker_id))
        self.redis.srem(self.index_key, worker_id)

    def _worker_key(self, worker_id: str) -> str:
        return f"{self.key_prefix}:{worker_id}"


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _field_value(fields: dict[Any, Any], key: str) -> Any:
    if key in fields:
        return fields[key]
    byte_key = key.encode("utf-8")
    if byte_key in fields:
        return fields[byte_key]
    raise KeyError(key)


def _leased_task_from_message(
    *,
    queue_name: str,
    message_id: Any,
    fields: dict[Any, Any],
    worker_id: str,
    reclaimed: bool = False,
) -> LeasedTask:
    raw_task = _field_value(fields, "task")
    task = Task.from_dict(json.loads(_decode(raw_task)))
    previous_worker = task.leased_by
    previous_attempts = task.attempts
    task.status = TaskStatus.LEASED
    task.leased_by = worker_id
    task.attempts += 1
    task.metadata["lease_count"] = task.attempts
    if reclaimed:
        task.metadata["reclaimed"] = True
        if previous_worker and previous_worker != worker_id:
            task.metadata["reclaimed_from_worker"] = previous_worker
        task.metadata["reclaimed_attempts_before"] = previous_attempts
    task.updated_at = datetime.now(UTC)
    if task.timeout_seconds is not None:
        task.lease_expires_at = task.updated_at + timedelta(seconds=task.timeout_seconds)
    return LeasedTask(
        queue_name=queue_name,
        message_id=_decode(message_id),
        task=task,
    )


def _pending_message_id(entry: Any) -> str:
    if isinstance(entry, dict):
        return _decode(_dict_value(entry, "message_id"))
    return _decode(entry[0])


def _pending_idle_ms(entry: Any) -> int:
    if isinstance(entry, dict):
        return int(_dict_value(entry, "time_since_delivered") or 0)
    return int(entry[2] or 0)


def _dict_value(data: dict[Any, Any], key: str) -> Any:
    if key in data:
        return data[key]
    byte_key = key.encode("utf-8")
    if byte_key in data:
        return data[byte_key]
    return None


def _non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _optional_decoded_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(_decode(value))
    return text or None


def _redacted_task_dict(task: Task) -> dict[str, Any]:
    payload = task.to_dict()
    payload["payload"] = _redact_secrets(payload.get("payload") or {})
    payload["metadata"] = _redact_secrets(payload.get("metadata") or {})
    return payload


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(
        token in normalized
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
        )
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    return datetime.now(UTC)
