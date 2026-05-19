import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from core.framework.workers import (
    BackpressurePolicy,
    InMemoryTaskQueue,
    QueueStatus,
    RedisStreamTaskQueue,
    Task,
    TaskEnqueueResult,
    TaskError,
    TaskRetryPolicy,
    TaskStatus,
)


def test_in_memory_queue_enqueue_lease_ack() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"})

    queue.enqueue(task)
    leased = queue.lease("worker-1", ["news:queue:daily"])

    assert leased is task
    assert leased.status == TaskStatus.LEASED
    assert queue.queue_status("news:queue:daily").leased_count == 1

    queue.ack(leased.task_id, "worker-1")

    assert leased.status == TaskStatus.SUCCEEDED
    assert queue.events[-1].event_type == "task_succeeded"
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


def test_in_memory_queue_backpressure_rejects_when_pending_limit_reached() -> None:
    queue = InMemoryTaskQueue(
        backpressure_policy=BackpressurePolicy(max_pending_per_queue=1)
    )
    first = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    second = Task(task_type="daily_intelligence.run", payload={"topic": "ML"}, task_id="task-2")

    accepted = queue.enqueue(first)
    rejected = queue.enqueue(second)

    assert accepted is None
    assert isinstance(rejected, TaskEnqueueResult)
    assert rejected.accepted is False
    assert rejected.reason == "backpressure"
    assert bool(rejected) is False
    assert queue.queue_status("news:queue:daily").pending_count == 1


def test_in_memory_queue_retry_delay_and_dead_letter_records_are_observable() -> None:
    now = datetime(2026, 5, 11, 1, 0, tzinfo=UTC)
    queue = InMemoryTaskQueue(
        retry_policy=TaskRetryPolicy(base_delay_seconds=30, max_delay_seconds=30),
        now_fn=lambda: now,
    )
    retry_task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="retry-task",
        max_attempts=2,
    )
    queue.enqueue(retry_task)
    leased = queue.lease("worker-1", ["news:queue:daily"])

    queue.fail(leased.task_id, "worker-1", TaskError("Timeout", "timeout"))

    assert retry_task.status == TaskStatus.QUEUED
    assert retry_task.scheduled_for == now + timedelta(seconds=30)
    assert queue.events[-1].event_type == "task_enqueued"
    assert any(event.event_type == "task_retry_scheduled" for event in queue.events)
    status = queue.queue_status("news:queue:daily")
    assert isinstance(status, QueueStatus)
    assert status.delayed_count == 1

    dead_letter_task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="dead-task",
        max_attempts=1,
    )
    queue.enqueue(dead_letter_task)
    leased_dead = queue.lease("worker-1", ["news:queue:daily"])
    queue.fail(leased_dead.task_id, "worker-1", TaskError("TaskFailed", "failed"))

    dead_letters = queue.list_dead_letters()
    assert dead_letters[0].task.task_id == "dead-task"
    assert dead_letters[0].attempts == 1
    assert dead_letters[0].last_event.event_type == "task_dead_lettered"


def test_in_memory_queue_cancels_queued_task() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    queue.enqueue(task)

    cancelled = queue.cancel("task-1", reason="operator")

    assert cancelled is True
    assert task.status == TaskStatus.CANCELLED
    assert task.metadata["cancel_reason"] == "operator"
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


def test_in_memory_queue_requeues_dead_letter_task() -> None:
    queue = InMemoryTaskQueue()
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        max_attempts=1,
    )
    queue.enqueue(task)
    leased = queue.lease("worker-1", ["news:queue:daily"])
    queue.fail(leased.task_id, "worker-1", TaskError("TaskFailed", "failed"))

    requeued = queue.requeue_dead_letter("task-1", reason="operator_retry")
    leased_again = queue.lease("worker-2", ["news:queue:daily"])

    assert requeued is True
    assert leased_again.task_id == "task-1"
    assert leased_again.metadata["requeue_reason"] == "operator_retry"
    assert leased_again.metadata["dead_letter_reason"] == "failed"
    assert leased_again.metadata["dead_letter_attempts"] == 1
    assert queue.list_dead_letters() == []


def test_in_memory_queue_retry_exhaustion_routes_directly_to_dead_letter() -> None:
    clock = {"now": datetime(2026, 5, 11, 1, 0, tzinfo=UTC)}
    queue = InMemoryTaskQueue(
        retry_policy=TaskRetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0),
        now_fn=lambda: clock["now"],
    )
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="exhaustion-task",
        max_attempts=2,
    )
    queue.enqueue(task)
    first = queue.lease("worker-1", ["news:queue:daily"])
    queue.fail(first.task_id, "worker-1", TaskError("Timeout", "timeout"))
    clock["now"] = clock["now"] + timedelta(minutes=1)
    second = queue.lease("worker-1", ["news:queue:daily"])
    queue.fail(second.task_id, "worker-1", TaskError("Timeout", "timeout"))

    dead_letters = queue.list_dead_letters()
    assert [record.task.task_id for record in dead_letters] == ["exhaustion-task"]
    assert dead_letters[0].attempts == 2
    assert dead_letters[0].task.status == TaskStatus.DEAD_LETTER


def test_in_memory_queue_requeued_task_re_failure_returns_to_dead_letter() -> None:
    queue = InMemoryTaskQueue(retry_policy=TaskRetryPolicy(max_attempts=1))
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="dl-task",
        max_attempts=1,
    )
    queue.enqueue(task)
    leased = queue.lease("worker-1", ["news:queue:daily"])
    queue.fail(leased.task_id, "worker-1", TaskError("TaskFailed", "failed"))

    queue.requeue_dead_letter("dl-task", reason="operator_retry")
    leased_again = queue.lease("worker-2", ["news:queue:daily"])
    queue.fail(leased_again.task_id, "worker-2", TaskError("TaskFailed", "failed"))

    dead_letters = queue.list_dead_letters()
    assert [record.task.task_id for record in dead_letters] == ["dl-task"]
    assert dead_letters[0].task.metadata["requeue_reason"] == "operator_retry"


def test_in_memory_queue_rejects_duplicate_unfinished_dedup_key() -> None:
    queue = InMemoryTaskQueue()
    first = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        dedup_key="daily:AI",
    )
    duplicate = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-2",
        dedup_key="daily:AI",
    )

    queue.enqueue(first)
    rejected = queue.enqueue(duplicate)

    assert rejected.accepted is False
    assert rejected.reason == "duplicate_dedup_key"


def test_in_memory_queue_reclaims_expired_lease() -> None:
    now = datetime(2026, 5, 11, 1, 0, tzinfo=UTC)
    queue = InMemoryTaskQueue(now_fn=lambda: now)
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        timeout_seconds=30,
    )
    queue.enqueue(task)
    queue.lease("worker-1", ["news:queue:daily"])

    reclaimed = queue.reclaim_stale(
        "worker-2",
        ["news:queue:daily"],
        now=now + timedelta(seconds=31),
    )

    assert reclaimed is task
    assert task.leased_by == "worker-2"
    assert task.metadata["reclaimed"] is True
    assert task.metadata["reclaimed_from_worker"] == "worker-1"
    assert task.metadata["lease_count"] == 1
    assert queue.events[-1].event_type == "task_reclaimed"


def test_redis_stream_queue_enqueue_uses_xadd() -> None:
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(redis)
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")

    message_id = queue.enqueue(task)

    assert message_id == "1-0"
    stream, payload = redis.xadd_calls[0]
    assert stream == "news:queue:daily"
    assert json.loads(payload["task"])["task_id"] == "task-1"


def test_redis_stream_queue_redacts_secret_payload_values() -> None:
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(redis)
    task = Task(
        task_type="daily_intelligence.run",
        payload={"api_key": "hidden", "nested": {"authorization": "Bearer hidden"}},
        task_id="task-1",
    )

    queue.enqueue(task)

    payload = json.loads(redis.xadd_calls[0][1]["task"])
    assert payload["payload"]["api_key"] == "[REDACTED]"
    assert payload["payload"]["nested"]["authorization"] == "[REDACTED]"


def test_redis_stream_queue_lease_one_decodes_task_payload() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    redis = _FakeRedisReader(task.to_dict())
    queue = RedisStreamTaskQueue(redis)

    leased = queue.lease_one("worker-1", ["news:queue:daily"], block_ms=10)

    assert leased.task.task_id == "task-1"
    assert leased.task.status == TaskStatus.LEASED
    assert leased.task.leased_by == "worker-1"
    assert leased.task.attempts == 1
    assert leased.task.metadata["lease_count"] == 1
    assert leased.queue_name == "news:queue:daily"
    assert leased.message_id == "1-0"


def test_redis_stream_queue_reclaim_stale_one_claims_pending_payload() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    task.leased_by = "worker-1"
    task.attempts = 1
    redis = _FakeRedisPending(task.to_dict(), idle_ms=120_000)
    queue = RedisStreamTaskQueue(redis)

    leased = queue.reclaim_stale_one(
        "worker-2",
        ["news:queue:daily"],
        min_idle_ms=60_000,
    )

    assert leased.task.task_id == "task-1"
    assert leased.task.status == TaskStatus.LEASED
    assert leased.task.leased_by == "worker-2"
    assert leased.task.attempts == 2
    assert leased.task.metadata["lease_count"] == 2
    assert leased.task.metadata["reclaimed"] is True
    assert leased.task.metadata["reclaimed_from_worker"] == "worker-1"
    assert leased.task.metadata["reclaimed_attempts_before"] == 1
    assert leased.queue_name == "news:queue:daily"
    assert leased.message_id == "1-0"
    assert redis.xclaim_calls == [
        ("news:queue:daily", "news-workers", "worker-2", 60_000, ["1-0"])
    ]


def test_redis_stream_queue_reclaim_stale_one_skips_fresh_pending_payload() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    redis = _FakeRedisPending(task.to_dict(), idle_ms=1_000)
    queue = RedisStreamTaskQueue(redis)

    leased = queue.reclaim_stale_one(
        "worker-2",
        ["news:queue:daily"],
        min_idle_ms=60_000,
    )

    assert leased is None
    assert redis.xclaim_calls == []


def test_redis_stream_queue_status_reads_pending_summary() -> None:
    redis = _FakeRedisStatus(
        stream_length=3,
        pending={
            "pending": 2,
            "consumers": [{"name": b"worker-1", "pending": 2}],
        },
    )
    queue = RedisStreamTaskQueue(redis)

    statuses = queue.status(["news:queue:daily"])

    payload = statuses[0].to_dict()
    assert payload["queue_name"] == "news:queue:daily"
    assert payload["stream_length"] == 3
    assert payload["group_exists"] is True
    assert payload["pending_count"] == 2
    assert payload["consumers"] == [{"consumer_name": "worker-1", "pending_count": 2}]


def test_redis_stream_queue_status_reports_missing_group() -> None:
    redis = _FakeRedisStatus(stream_length=1, pending_error=Exception("NOGROUP missing"))
    queue = RedisStreamTaskQueue(redis)

    statuses = queue.status(["news:queue:daily"])

    payload = statuses[0].to_dict()
    assert payload["stream_length"] == 1
    assert payload["group_exists"] is False
    assert payload["pending_count"] == 0


def test_redis_stream_queue_fail_retries_and_acks_original_message() -> None:
    task = Task(task_type="daily_intelligence.run", payload={}, task_id="task-1", attempts=1)
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(
        redis,
        retry_policy=TaskRetryPolicy(retryable_error_types=["Timeout"], base_delay_seconds=5),
    )

    result = queue.fail(_leased(task), TaskError("Timeout", "temporary timeout"))

    assert result.accepted is True
    assert result.status == TaskStatus.RETRYING
    assert redis.xack_calls == [("news:queue:daily", "news-workers", "1-0")]
    assert json.loads(redis.xadd_calls[0][1]["task"])["metadata"]["retry_next_run_at"]


def test_redis_stream_queue_fail_dead_letters_quality_gate_block_without_retry() -> None:
    task = Task(task_type="daily_intelligence.run", payload={}, task_id="task-blocked", attempts=1)
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(
        redis,
        retry_policy=TaskRetryPolicy(retryable_error_types=["Timeout"], base_delay_seconds=5),
    )

    result = queue.fail(
        _leased(task),
        TaskError("QualityGateBlocked", "quality gate blocked", retryable=False),
    )

    assert result.status == TaskStatus.DEAD_LETTER
    assert redis.xack_calls == [("news:queue:daily", "news-workers", "1-0")]
    assert queue.list_dead_letters()[0].error.error_type == "QualityGateBlocked"


def test_redis_stream_queue_fail_dead_letters_and_requeues_record() -> None:
    task = Task(task_type="daily_intelligence.run", payload={}, task_id="task-1", attempts=3)
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(redis)

    result = queue.fail(_leased(task), TaskError("ValidationError", "bad input", retryable=False))
    dead_letters = queue.list_dead_letters()
    requeued = queue.requeue_dead_letter("task-1", reason="operator_retry")

    assert result.status == TaskStatus.DEAD_LETTER
    assert dead_letters[0].task.task_id == "task-1"
    assert dead_letters[0].error.error_type == "ValidationError"
    assert dead_letters[0].last_event.event_type == "task_dead_lettered"
    assert requeued is True
    assert redis.xack_calls == [("news:queue:daily", "news-workers", "1-0")]
    assert redis.xdel_calls == [("news:queue:dead-letter", "1-0")]
    assert json.loads(redis.xadd_calls[-1][1]["task"])["metadata"]["requeue_reason"] == "operator_retry"


@pytest.mark.skipif(
    os.getenv("NEWSROOM_WORKER_REDIS_TESTS") != "1",
    reason="set NEWSROOM_WORKER_REDIS_TESTS=1 to run Redis stream integration tests",
)
def test_redis_stream_queue_integration_ack_reclaim_and_dlq() -> None:
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(os.getenv("NEWSROOM_REDIS_URL", "redis://localhost:6379/15"))
    client.ping()
    queue_name = "news:test:queue:daily"
    dlq_name = "news:test:queue:dead-letter"
    client.delete(queue_name, dlq_name)
    queue = RedisStreamTaskQueue(
        client,
        group_name="news-test-workers",
        dead_letter_queue_name=dlq_name,
    )

    acked = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, queue_name=queue_name)
    queue.enqueue(acked)
    leased = queue.lease_one("worker-1", [queue_name], block_ms=10)
    queue.ack(leased.queue_name, leased.message_id)

    pending = Task(task_type="daily_intelligence.run", payload={"topic": "ML"}, queue_name=queue_name)
    queue.enqueue(pending)
    queue.lease_one("worker-1", [queue_name], block_ms=10)
    reclaimed = queue.reclaim_stale_one("worker-2", [queue_name], min_idle_ms=0)
    failed = queue.fail(
        reclaimed,
        TaskError("ValidationError", "bad input", retryable=False),
    )

    assert failed.status == TaskStatus.DEAD_LETTER
    assert queue.list_dead_letters()[0].task.task_id == pending.task_id
    assert queue.status([queue_name])[0].group_exists is True


class _FakeRedis:
    def __init__(self) -> None:
        self.xadd_calls = []
        self.xack_calls = []
        self.xdel_calls = []
        self.streams = {}

    def xadd(self, stream, payload):
        self.xadd_calls.append((stream, payload))
        message_id = f"{len(self.streams.get(stream, [])) + 1}-0"
        self.streams.setdefault(stream, []).append((message_id, payload))
        return message_id

    def xack(self, stream, group, message_id):
        self.xack_calls.append((stream, group, message_id))
        return 1

    def xrange(self, stream, min, max, count):
        return list(self.streams.get(stream, []))[:count]

    def xdel(self, stream, message_id):
        self.xdel_calls.append((stream, message_id))
        self.streams[stream] = [
            record for record in self.streams.get(stream, []) if record[0] != message_id
        ]
        return 1


class _FakeRedisReader:
    def __init__(self, task_payload) -> None:
        self.task_payload = task_payload
        self.xgroup_create_calls = []

    def xgroup_create(self, stream, group, id, mkstream):
        self.xgroup_create_calls.append((stream, group, id, mkstream))

    def xreadgroup(self, group, consumer, streams, count, block):
        payload = json.dumps(self.task_payload).encode("utf-8")
        return [(b"news:queue:daily", [(b"1-0", {b"task": payload})])]


class _FakeRedisPending:
    def __init__(self, task_payload, *, idle_ms) -> None:
        self.task_payload = task_payload
        self.idle_ms = idle_ms
        self.xgroup_create_calls = []
        self.xpending_range_calls = []
        self.xclaim_calls = []

    def xgroup_create(self, stream, group, id, mkstream):
        self.xgroup_create_calls.append((stream, group, id, mkstream))

    def xpending_range(self, stream, group, min, max, count):
        self.xpending_range_calls.append((stream, group, min, max, count))
        return [{"message_id": b"1-0", "time_since_delivered": self.idle_ms}]

    def xclaim(self, stream, group, consumer, min_idle_ms, message_ids):
        self.xclaim_calls.append((stream, group, consumer, min_idle_ms, list(message_ids)))
        payload = json.dumps(self.task_payload).encode("utf-8")
        return [(b"1-0", {b"task": payload})]


class _FakeRedisStatus:
    def __init__(self, *, stream_length, pending=None, pending_error=None) -> None:
        self.stream_length = stream_length
        self.pending = pending or {"pending": 0, "consumers": []}
        self.pending_error = pending_error
        self.xlen_calls = []
        self.xpending_calls = []

    def xlen(self, stream):
        self.xlen_calls.append(stream)
        return self.stream_length

    def xpending(self, stream, group):
        self.xpending_calls.append((stream, group))
        if self.pending_error:
            raise self.pending_error
        return self.pending


def _leased(task):
    from core.framework.workers import LeasedTask

    return LeasedTask(queue_name="news:queue:daily", message_id="1-0", task=task)
