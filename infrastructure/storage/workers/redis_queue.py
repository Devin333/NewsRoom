from __future__ import annotations

import json
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from framework.shared.public_errors import sanitize_public_error_fields

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
    StaleTaskLeaseError,
    task_admission_error,
)
from framework.workers.runtime.heartbeat import WorkerHeartbeat, WorkerHeartbeatStatus


_LEASE_SCRIPT_VERSION = "v1"

_ACQUIRE_LEASE_SCRIPT = r"""
-- newsroom:worker-lease-v1:acquire
local stamp = redis.call('TIME')
local now_ms = (tonumber(stamp[1]) * 1000) + math.floor(tonumber(stamp[2]) / 1000)
local state = redis.call('HGET', KEYS[1], 'state')
local current_lease = redis.call('HGET', KEYS[1], 'lease_id')
if state == 'active' and current_lease == ARGV[7] and redis.call('HGET', KEYS[1], 'owner') == ARGV[6] then
  return {'ok', redis.call('HGET', KEYS[1], 'fencing_token'), redis.call('HGET', KEYS[1], 'attempt'), redis.call('HGET', KEYS[1], 'expires_at_ms')}
end
if state == 'active' and tonumber(redis.call('HGET', KEYS[1], 'expires_at_ms') or '0') > now_ms then
  return {'busy'}
end
if state and state ~= 'active' then
  return {'terminal'}
end
if not redis.call('HGET', KEYS[2], 'attempt') then
  redis.call('HSET', KEYS[2], 'attempt', tonumber(ARGV[9]))
end
local fencing = redis.call('HINCRBY', KEYS[2], 'fencing_token', 1)
local attempt = redis.call('HINCRBY', KEYS[2], 'attempt', 1)
local expires_at_ms = now_ms + tonumber(ARGV[8])
redis.call('HSET', KEYS[1],
  'version', ARGV[1], 'task_id', ARGV[2], 'queue', ARGV[3], 'group', ARGV[4],
  'message_id', ARGV[5], 'owner', ARGV[6], 'lease_id', ARGV[7],
  'fencing_token', fencing, 'attempt', attempt, 'expires_at_ms', expires_at_ms, 'state', 'active')
return {'ok', fencing, attempt, expires_at_ms}
"""

_RECLAIM_LEASE_SCRIPT = r"""
-- newsroom:worker-lease-v1:reclaim
local stamp = redis.call('TIME')
local now_ms = (tonumber(stamp[1]) * 1000) + math.floor(tonumber(stamp[2]) / 1000)
local state = redis.call('HGET', KEYS[2], 'state')
if state == 'active' and tonumber(redis.call('HGET', KEYS[2], 'expires_at_ms') or '0') > now_ms then
  return {'busy'}
end
if state and state ~= 'active' then
  return {'terminal'}
end
local claimed = redis.call('XCLAIM', KEYS[1], ARGV[1], ARGV[4], 0, ARGV[2])
if #claimed == 0 then
  return {'missing'}
end
if not redis.call('HGET', KEYS[3], 'attempt') then
  redis.call('HSET', KEYS[3], 'attempt', tonumber(ARGV[8]))
end
local fencing = redis.call('HINCRBY', KEYS[3], 'fencing_token', 1)
local attempt = redis.call('HINCRBY', KEYS[3], 'attempt', 1)
local expires_at_ms = now_ms + tonumber(ARGV[6])
redis.call('HSET', KEYS[2],
  'version', ARGV[7], 'task_id', ARGV[3], 'queue', KEYS[1], 'group', ARGV[1],
  'message_id', ARGV[2], 'owner', ARGV[4], 'lease_id', ARGV[5],
  'fencing_token', fencing, 'attempt', attempt, 'expires_at_ms', expires_at_ms, 'state', 'active')
return {'ok', fencing, attempt, expires_at_ms}
"""

_RENEW_LEASE_SCRIPT = r"""
-- newsroom:worker-lease-v1:renew
local stamp = redis.call('TIME')
local now_ms = (tonumber(stamp[1]) * 1000) + math.floor(tonumber(stamp[2]) / 1000)
if redis.call('HGET', KEYS[1], 'state') ~= 'active'
  or redis.call('HGET', KEYS[1], 'queue') ~= ARGV[1]
  or redis.call('HGET', KEYS[1], 'group') ~= ARGV[2]
  or redis.call('HGET', KEYS[1], 'message_id') ~= ARGV[3]
  or redis.call('HGET', KEYS[1], 'owner') ~= ARGV[4]
  or redis.call('HGET', KEYS[1], 'lease_id') ~= ARGV[5]
  or tonumber(redis.call('HGET', KEYS[1], 'fencing_token') or '-1') ~= tonumber(ARGV[6])
  or tonumber(redis.call('HGET', KEYS[1], 'expires_at_ms') or '0') <= now_ms then
  return {'stale'}
end
local expires_at_ms = now_ms + tonumber(ARGV[7])
redis.call('HSET', KEYS[1], 'expires_at_ms', expires_at_ms)
return {'ok', expires_at_ms}
"""

_COMPLETE_LEASE_SCRIPT = r"""
-- newsroom:worker-lease-v1:complete
local state = redis.call('HGET', KEYS[2], 'state')
if state == ARGV[7]
  and redis.call('HGET', KEYS[2], 'queue') == ARGV[1]
  and redis.call('HGET', KEYS[2], 'group') == ARGV[2]
  and redis.call('HGET', KEYS[2], 'message_id') == ARGV[3]
  and redis.call('HGET', KEYS[2], 'owner') == ARGV[4]
  and redis.call('HGET', KEYS[2], 'lease_id') == ARGV[5]
  and tonumber(redis.call('HGET', KEYS[2], 'fencing_token') or '-1') == tonumber(ARGV[6]) then
  return {'complete', redis.call('HGET', KEYS[2], 'terminal_message_id') or ''}
end
if state and state ~= 'active' then
  return {'stale'}
end
local pending = redis.call('XPENDING', KEYS[1], ARGV[2], ARGV[3], ARGV[3], 1)
if #pending == 0 then
  return {'stale'}
end
local stamp = redis.call('TIME')
local now_ms = (tonumber(stamp[1]) * 1000) + math.floor(tonumber(stamp[2]) / 1000)
if state ~= 'active'
  or redis.call('HGET', KEYS[2], 'queue') ~= ARGV[1]
  or redis.call('HGET', KEYS[2], 'group') ~= ARGV[2]
  or redis.call('HGET', KEYS[2], 'message_id') ~= ARGV[3]
  or redis.call('HGET', KEYS[2], 'owner') ~= ARGV[4]
  or redis.call('HGET', KEYS[2], 'lease_id') ~= ARGV[5]
  or tonumber(redis.call('HGET', KEYS[2], 'fencing_token') or '-1') ~= tonumber(ARGV[6])
  or tonumber(redis.call('HGET', KEYS[2], 'expires_at_ms') or '0') <= now_ms then
  return {'stale'}
end
local acked = redis.call('XACK', KEYS[1], ARGV[2], ARGV[3])
if acked ~= 1 then
  return {'stale'}
end
redis.call('HSET', KEYS[2], 'state', ARGV[7], 'completed_at_ms', now_ms)
return {'ok', ''}
"""

_TRANSITION_LEASE_SCRIPT = r"""
-- newsroom:worker-lease-v1:transition
local state = redis.call('HGET', KEYS[2], 'state')
if state == ARGV[7]
  and redis.call('HGET', KEYS[2], 'queue') == ARGV[1]
  and redis.call('HGET', KEYS[2], 'group') == ARGV[2]
  and redis.call('HGET', KEYS[2], 'message_id') == ARGV[3]
  and redis.call('HGET', KEYS[2], 'owner') == ARGV[4]
  and redis.call('HGET', KEYS[2], 'lease_id') == ARGV[5]
  and tonumber(redis.call('HGET', KEYS[2], 'fencing_token') or '-1') == tonumber(ARGV[6]) then
  return {'complete', redis.call('HGET', KEYS[2], 'terminal_message_id') or ''}
end
if state and state ~= 'active' then
  return {'stale'}
end
local pending = redis.call('XPENDING', KEYS[1], ARGV[2], ARGV[3], ARGV[3], 1)
if #pending == 0 then
  return {'stale'}
end
local target_type = redis.call('TYPE', KEYS[3])['ok']
if target_type ~= 'none' and target_type ~= 'stream' then
  return {'target_type_error'}
end
local stamp = redis.call('TIME')
local now_ms = (tonumber(stamp[1]) * 1000) + math.floor(tonumber(stamp[2]) / 1000)
if state ~= 'active'
  or redis.call('HGET', KEYS[2], 'queue') ~= ARGV[1]
  or redis.call('HGET', KEYS[2], 'group') ~= ARGV[2]
  or redis.call('HGET', KEYS[2], 'message_id') ~= ARGV[3]
  or redis.call('HGET', KEYS[2], 'owner') ~= ARGV[4]
  or redis.call('HGET', KEYS[2], 'lease_id') ~= ARGV[5]
  or tonumber(redis.call('HGET', KEYS[2], 'fencing_token') or '-1') ~= tonumber(ARGV[6])
  or tonumber(redis.call('HGET', KEYS[2], 'expires_at_ms') or '0') <= now_ms then
  return {'stale'}
end
local next_id = redis.call('XADD', KEYS[3], '*', 'task', ARGV[8])
local acked = redis.call('XACK', KEYS[1], ARGV[2], ARGV[3])
if acked ~= 1 then
  return {'stale'}
end
redis.call('HSET', KEYS[2], 'state', ARGV[7], 'completed_at_ms', now_ms, 'terminal_message_id', next_id)
return {'ok', next_id}
"""


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
        lease_ttl_ms: int = 60_000,
        lease_key_prefix: str = "news:worker-leases",
    ) -> None:
        if lease_ttl_ms <= 0:
            raise ValueError("lease_ttl_ms must be greater than zero")
        self.redis = redis_client
        self.group_name = group_name
        self.dead_letter_queue_name = dead_letter_queue_name
        self.retry_policy = retry_policy or TaskRetryPolicy()
        self.lease_ttl_ms = int(lease_ttl_ms)
        self.lease_key_prefix = lease_key_prefix.rstrip(":")

    def enqueue(self, task: Task) -> str | TaskEnqueueResult:
        admission_error = task_admission_error(task)
        if admission_error is not None:
            return TaskEnqueueResult(
                task_id=task.task_id,
                queue_name=task.queue_name,
                accepted=False,
                status=task.status,
                reason=admission_error[0],
            )
        from framework.events import current_trace_context, inject_current_trace

        if current_trace_context() is not None:
            task.trace_carrier = inject_current_trace(task.trace_carrier)
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
                decoded_message_id = _decode(message_id)
                raw_task = _field_value(fields, "task")
                task = Task.from_dict(json.loads(_decode(raw_task)))
                lease_id = uuid4().hex
                acquired = self._eval_script(
                    _ACQUIRE_LEASE_SCRIPT,
                    keys=[
                        self._lease_key(decoded_queue_name, decoded_message_id),
                        self._counter_key(task.task_id),
                    ],
                    args=[
                        _LEASE_SCRIPT_VERSION,
                        task.task_id,
                        decoded_queue_name,
                        self.group_name,
                        decoded_message_id,
                        worker_id,
                        lease_id,
                        self._lease_ttl_for(task),
                        max(0, task.attempts),
                    ],
                )
                if _script_status(acquired) != "ok":
                    return None
                return _leased_task_from_state(
                    queue_name=decoded_queue_name,
                    message_id=decoded_message_id,
                    task=task,
                    worker_id=worker_id,
                    lease_id=lease_id,
                    script_result=acquired,
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
            for message_id in stale_ids:
                records = self.redis.xrange(queue_name, min=message_id, max=message_id, count=1)
                if not records:
                    continue
                _stored_id, fields = records[0]
                task = Task.from_dict(json.loads(_decode(_field_value(fields, "task"))))
                lease_id = uuid4().hex
                reclaimed = self._eval_script(
                    _RECLAIM_LEASE_SCRIPT,
                    keys=[
                        queue_name,
                        self._lease_key(queue_name, message_id),
                        self._counter_key(task.task_id),
                    ],
                    args=[
                        self.group_name,
                        message_id,
                        task.task_id,
                        worker_id,
                        lease_id,
                        self._lease_ttl_for(task),
                        _LEASE_SCRIPT_VERSION,
                        max(0, task.attempts),
                    ],
                )
                if _script_status(reclaimed) == "ok":
                    return _leased_task_from_state(
                        queue_name=queue_name,
                        message_id=message_id,
                        task=task,
                        worker_id=worker_id,
                        lease_id=lease_id,
                        script_result=reclaimed,
                        reclaimed=True,
                    )
        return None

    def renew(self, leased: LeasedTask) -> datetime:
        self._require_fenced(leased, operation="renew")
        result = self._eval_script(
            _RENEW_LEASE_SCRIPT,
            keys=[self._lease_key(leased.queue_name, leased.message_id)],
            args=[
                leased.queue_name,
                self.group_name,
                leased.message_id,
                leased.owner_id,
                leased.lease_id,
                leased.fencing_token,
                self._lease_ttl_for(leased.task),
            ],
        )
        if _script_status(result) != "ok":
            raise StaleTaskLeaseError(leased, operation="renew")
        lease_expires_at = _datetime_from_ms(_script_int(result, 1))
        leased.task.lease_expires_at = lease_expires_at
        object.__setattr__(leased, "lease_expires_at", lease_expires_at)
        return lease_expires_at

    def ack(self, leased: LeasedTask) -> int:
        if not isinstance(leased, LeasedTask):
            raise TypeError("fenced LeasedTask is required")
        self._require_fenced(leased, operation="ack")
        result = self._complete(leased, state="succeeded")
        if _script_status(result) not in {"ok", "complete"}:
            raise StaleTaskLeaseError(leased, operation="ack")
        return 1

    def _complete(self, leased: LeasedTask, *, state: str) -> list[Any]:
        return self._eval_script(
            _COMPLETE_LEASE_SCRIPT,
            keys=[
                leased.queue_name,
                self._lease_key(leased.queue_name, leased.message_id),
            ],
            args=[
                leased.queue_name,
                self.group_name,
                leased.message_id,
                leased.owner_id,
                leased.lease_id,
                leased.fencing_token,
                state,
            ],
        )

    def _transition(
        self,
        leased: LeasedTask,
        *,
        target_queue: str,
        state: str,
        payload: dict[str, Any],
    ) -> list[Any]:
        return self._eval_script(
            _TRANSITION_LEASE_SCRIPT,
            keys=[
                leased.queue_name,
                self._lease_key(leased.queue_name, leased.message_id),
                target_queue,
            ],
            args=[
                leased.queue_name,
                self.group_name,
                leased.message_id,
                leased.owner_id,
                leased.lease_id,
                leased.fencing_token,
                state,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ],
        )

    def _require_fenced(self, leased: LeasedTask, *, operation: str) -> None:
        if (
            not leased.is_fenced
            or not leased.owner_id
            or leased.attempt is None
            or leased.fencing_token is None
        ):
            raise StaleTaskLeaseError(leased, operation=operation)

    def _eval_script(self, script: str, *, keys: list[Any], args: list[Any]) -> list[Any]:
        if not hasattr(self.redis, "eval"):
            raise RuntimeError("Redis scripting is required for fenced task leases")
        result = self.redis.eval(script, len(keys), *keys, *args)
        if not isinstance(result, (list, tuple)) or not result:
            raise RuntimeError("invalid Redis lease script response")
        return [_decode(item) for item in result]

    def _lease_key(self, queue_name: str, message_id: str) -> str:
        identity = sha256(
            f"{queue_name}\0{self.group_name}\0{message_id}".encode("utf-8")
        ).hexdigest()
        return f"{self.lease_key_prefix}:{_LEASE_SCRIPT_VERSION}:lease:{identity}"

    def _counter_key(self, task_id: str) -> str:
        identity = sha256(task_id.encode("utf-8")).hexdigest()
        return f"{self.lease_key_prefix}:{_LEASE_SCRIPT_VERSION}:task:{identity}"

    def _lease_ttl_for(self, task: Task) -> int:
        return self.lease_ttl_ms

    def renewal_interval_seconds(self, leased: LeasedTask) -> float:
        del leased
        return self.lease_ttl_ms / 1000 / 4

    def fail(self, leased: LeasedTask, error: TaskError) -> TaskEnqueueResult:
        self._require_fenced(leased, operation="fail")
        task = leased.task
        safe_error = _safe_task_error(error)
        if self.retry_policy.should_retry(task, error):
            next_run_at = self.retry_policy.next_run_at(task)
            task.status = TaskStatus.RETRYING
            task.scheduled_for = next_run_at
            task.metadata["retry_next_run_at"] = next_run_at.isoformat().replace("+00:00", "Z")
            payload = _redacted_task_dict(task)
            result = self._transition(
                leased,
                target_queue=task.queue_name,
                state="retrying",
                payload=payload,
            )
            if _script_status(result) not in {"ok", "complete"}:
                raise StaleTaskLeaseError(leased, operation="retry")
            message_id = str(result[1])
            return TaskEnqueueResult(
                task_id=task.task_id,
                queue_name=task.queue_name,
                accepted=True,
                status=TaskStatus.RETRYING,
                message_id=str(message_id),
                delayed_until=next_run_at,
            )
        task.status = TaskStatus.DEAD_LETTER
        task.updated_at = datetime.now(UTC)
        payload = _dead_letter_payload(
            task,
            safe_error,
            source_queue=leased.queue_name,
            source_message_id=leased.message_id,
        )
        result = self._transition(
            leased,
            target_queue=self.dead_letter_queue_name,
            state="dead_letter",
            payload=payload,
        )
        if _script_status(result) not in {"ok", "complete"}:
            raise StaleTaskLeaseError(leased, operation="dead_letter")
        message_id = str(result[1])
        return TaskEnqueueResult(
            task_id=task.task_id,
            queue_name=self.dead_letter_queue_name,
            accepted=True,
            status=TaskStatus.DEAD_LETTER,
            message_id=str(message_id),
            reason=safe_error.error_message,
        )

    def move_to_dead_letter(self, task: Task, reason: str, error: TaskError | None = None) -> str:
        """Administrative DLQ insertion for an unleased task.

        Worker execution must call :meth:`fail` so ownership comparison, DLQ
        write and source ACK happen in one fenced server-side transition.
        """
        task.status = TaskStatus.DEAD_LETTER
        task.updated_at = datetime.now(UTC)
        task_error = error or TaskError("TaskFailed", reason, retryable=False)
        payload = _dead_letter_payload(task, _safe_task_error(task_error))
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

    def requeue_dead_letter(
        self,
        task_id: str,
        *,
        reason: str = "manual_requeue",
        replacement_payload: dict[str, Any] | None = None,
    ) -> bool:
        records = self.redis.xrange(self.dead_letter_queue_name, min="-", max="+", count=1000)
        for message_id, fields in records or []:
            payload = json.loads(_decode(_field_value(fields, "task")))
            if str(payload.get("task_id")) != task_id:
                continue
            if payload.get("metadata", {}).get("business_payload_redacted") is True:
                if replacement_payload is None:
                    return False
                _reject_secret_payload_keys(replacement_payload)
            task = Task.from_dict(payload)
            task.payload = dict(replacement_payload or task.payload)
            task.metadata = {
                "dead_letter_attempts": int(payload.get("attempts") or task.attempts),
                "dead_letter_error_id": (
                    (payload.get("dead_letter_error") or {}).get("error_id")
                ),
            }
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


def _leased_task_from_state(
    *,
    queue_name: str,
    message_id: str,
    task: Task,
    worker_id: str,
    lease_id: str,
    script_result: list[Any],
    reclaimed: bool = False,
) -> LeasedTask:
    previous_worker = task.leased_by
    previous_attempts = task.attempts
    fencing_token = _script_int(script_result, 1)
    attempt = _script_int(script_result, 2)
    lease_expires_at = _datetime_from_ms(_script_int(script_result, 3))
    task.status = TaskStatus.LEASED
    task.leased_by = worker_id
    task.attempts = attempt
    task.lease_expires_at = lease_expires_at
    task.metadata["lease_count"] = attempt
    task.metadata["lease_id"] = lease_id
    task.metadata["fencing_token"] = fencing_token
    task.metadata["effect_key"] = f"task:{task.task_id}"
    if reclaimed:
        task.metadata["reclaimed"] = True
        if previous_worker and previous_worker != worker_id:
            task.metadata["reclaimed_from_worker"] = previous_worker
        task.metadata["reclaimed_attempts_before"] = previous_attempts
    task.updated_at = datetime.now(UTC)
    return LeasedTask(
        queue_name=queue_name,
        message_id=message_id,
        task=task,
        owner_id=worker_id,
        lease_id=lease_id,
        fencing_token=fencing_token,
        attempt=attempt,
        lease_expires_at=lease_expires_at,
        effect_key=f"task:{task.task_id}",
    )


def _script_status(result: list[Any]) -> str:
    return str(_decode(result[0])) if result else ""


def _script_int(result: list[Any], index: int) -> int:
    try:
        return int(_decode(result[index]))
    except (IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("invalid Redis lease script response") from exc


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


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


def _safe_task_error(error: TaskError) -> TaskError:
    fields = sanitize_public_error_fields(
        error_type=error.error_type,
        error_message=error.error_message,
        error_id=error.error_id,
        context="worker",
    )
    return TaskError(
        error_type=str(fields["error_type"]),
        error_message=str(fields["error_message"]),
        retryable=error.retryable,
        operator_action_required=error.operator_action_required,
        error_id=fields["error_id"],
    )


def _dead_letter_payload(
    task: Task,
    error: TaskError,
    *,
    source_queue: str | None = None,
    source_message_id: str | None = None,
) -> dict[str, Any]:
    # DLQ is a diagnostic boundary, not a second business-payload store. Keep
    # only typed operational fields plus a digest; manual requeue resolves the
    # original immutable stream record by its safe queue/message reference.
    raw_payload = json.dumps(task.payload, ensure_ascii=False, sort_keys=True, default=str)
    payload = {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "queue": task.queue_name,
        "queue_name": task.queue_name,
        "payload": {},
        "status": TaskStatus.DEAD_LETTER.value,
        "attempt": task.attempts,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "priority": task.priority,
        "timeout_seconds": task.timeout_seconds,
        "dedup_key": None,
        "trace_id": None,
        "execution_scope": (
            task.execution_scope.value if task.execution_scope is not None else None
        ),
        "graph_identity": (
            task.graph_identity.to_dict() if task.graph_identity is not None else None
        ),
        "leased_by": None,
        "lease_expires_at": None,
        "run_at": None,
        "scheduled_for": None,
        "metadata": {
            "business_payload_redacted": True,
            "business_payload_sha256": sha256(raw_payload.encode("utf-8")).hexdigest(),
        },
        "created_at": task.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": task.updated_at.isoformat().replace("+00:00", "Z"),
    }
    payload["dead_letter_reason"] = error.error_message
    payload["dead_letter_error"] = error.to_dict()
    payload["dead_letter_source_queue"] = source_queue
    payload["dead_letter_source_message_id"] = source_message_id
    payload["dead_letter_failed_at"] = task.updated_at.isoformat().replace("+00:00", "Z")
    payload["dead_letter_last_event"] = TaskEvent(
        event_type="task_dead_lettered",
        task_id=task.task_id,
        task_status=TaskStatus.DEAD_LETTER,
        queue_name=task.queue_name,
        payload={"error": error.to_dict()},
        occurred_at=task.updated_at,
    ).to_dict()
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


def _reject_secret_payload_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_secret_key(str(key)):
                raise ValueError(f"replacement payload key is not allowed: {key}")
            _reject_secret_payload_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_payload_keys(item)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC)
    return datetime.now(UTC)
