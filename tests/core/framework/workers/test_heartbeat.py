from datetime import UTC, datetime

from core.framework.workers import (
    InMemoryTaskQueue,
    RedisWorkerRegistry,
    Task,
    WorkerHeartbeat,
    WorkerHeartbeatStatus,
    WorkerStatus,
)


def test_worker_heartbeat_round_trips_status() -> None:
    heartbeat = WorkerHeartbeat(
        worker_id="worker-1",
        queue_names=["news:queue:daily"],
        status=WorkerStatus.RUNNING,
        started_at=_dt("2026-05-11T00:00:00Z"),
        last_heartbeat_at=_dt("2026-05-11T00:00:05Z"),
        current_task_id="task-1",
        processed_count=2,
        failed_count=1,
        metadata={"host": "local"},
    )

    restored = WorkerHeartbeat.from_dict(heartbeat.to_dict())

    assert restored == heartbeat


def test_worker_heartbeat_status_marks_stale_as_unhealthy() -> None:
    heartbeat = WorkerHeartbeat(
        worker_id="worker-1",
        queue_names=["news:queue:daily"],
        status=WorkerStatus.RUNNING,
        last_heartbeat_at=_dt("2026-05-11T00:00:00Z"),
    )

    status = WorkerHeartbeatStatus.from_record(
        heartbeat,
        now=_dt("2026-05-11T00:02:00Z"),
        stale_after_seconds=60,
    )

    assert status.stale is True
    assert status.status == WorkerStatus.UNHEALTHY
    assert status.to_dict()["stored_status"] == "running"
    assert heartbeat.queues == ["news:queue:daily"]
    assert heartbeat.to_dict()["queues"] == ["news:queue:daily"]


def test_redis_worker_registry_saves_gets_and_lists_workers() -> None:
    redis = _FakeRedis()
    registry = RedisWorkerRegistry(redis)
    heartbeat = WorkerHeartbeat(
        worker_id="worker-1",
        queue_names=["news:queue:daily"],
        last_heartbeat_at=_dt("2026-05-11T00:00:00Z"),
    )

    registry.heartbeat(heartbeat)

    assert registry.get("worker-1") == heartbeat
    assert registry.list() == [heartbeat]
    assert registry.status(
        "worker-1",
        now=_dt("2026-05-11T00:01:01Z"),
        stale_after_seconds=60,
    ).status == WorkerStatus.UNHEALTHY
    assert registry.list_statuses(
        now=_dt("2026-05-11T00:01:01Z"),
        stale_after_seconds=60,
    )[0].stale is True


def test_redis_worker_registry_cleans_missing_index_entries() -> None:
    redis = _FakeRedis()
    registry = RedisWorkerRegistry(redis)
    redis.sadd(registry.index_key, "missing-worker")

    assert registry.list() == []
    assert redis.sets[registry.index_key] == set()


def test_stale_worker_pending_task_can_be_reclaimed() -> None:
    queue = InMemoryTaskQueue(now_fn=lambda: _dt("2026-05-11T00:00:00Z"))
    task = Task(
        task_type="daily_intelligence.run",
        payload={"topic": "AI"},
        task_id="task-1",
        timeout_seconds=30,
    )
    queue.enqueue(task)
    queue.lease("worker-1", ["news:queue:daily"])
    heartbeat = WorkerHeartbeat(
        worker_id="worker-1",
        queue_names=["news:queue:daily"],
        current_task_id="task-1",
        last_heartbeat_at=_dt("2026-05-11T00:00:00Z"),
    )

    status = WorkerHeartbeatStatus.from_record(
        heartbeat,
        now=_dt("2026-05-11T00:02:00Z"),
        stale_after_seconds=60,
    )
    reclaimed = queue.reclaim_stale(
        "worker-2",
        ["news:queue:daily"],
        now=_dt("2026-05-11T00:02:00Z"),
    )

    assert status.stale is True
    assert reclaimed is task
    assert reclaimed.leased_by == "worker-2"


class _FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.sets = {}

    def set(self, key, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)
        return 1

    def delete(self, key):
        self.values.pop(key, None)
        return 1


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
