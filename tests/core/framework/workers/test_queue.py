import json

from core.framework.workers import InMemoryTaskQueue, RedisStreamTaskQueue, Task, TaskError, TaskStatus


def test_in_memory_queue_enqueue_lease_ack() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"})

    queue.enqueue(task)
    leased = queue.lease("worker-1", ["news:queue:daily"])
    queue.ack(leased.task_id, "worker-1")

    assert leased is task
    assert leased.status == TaskStatus.LEASED
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


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


def test_redis_stream_queue_enqueue_uses_xadd() -> None:
    redis = _FakeRedis()
    queue = RedisStreamTaskQueue(redis)
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")

    message_id = queue.enqueue(task)

    assert message_id == "1-0"
    stream, payload = redis.xadd_calls[0]
    assert stream == "news:queue:daily"
    assert json.loads(payload["task"])["task_id"] == "task-1"


def test_redis_stream_queue_lease_one_decodes_task_payload() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
    redis = _FakeRedisReader(task.to_dict())
    queue = RedisStreamTaskQueue(redis)

    leased = queue.lease_one("worker-1", ["news:queue:daily"], block_ms=10)

    assert leased.task.task_id == "task-1"
    assert leased.task.status == TaskStatus.LEASED
    assert leased.task.leased_by == "worker-1"
    assert leased.task.attempts == 1
    assert leased.queue_name == "news:queue:daily"
    assert leased.message_id == "1-0"


def test_redis_stream_queue_reclaim_stale_one_claims_pending_payload() -> None:
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"}, task_id="task-1")
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
    assert leased.task.attempts == 1
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


class _FakeRedis:
    def __init__(self) -> None:
        self.xadd_calls = []

    def xadd(self, stream, payload):
        self.xadd_calls.append((stream, payload))
        return "1-0"


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
