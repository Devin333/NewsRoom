import json

from core.framework.workers import InMemoryTaskQueue, RedisStreamTaskQueue, Task, TaskStatus


def test_in_memory_queue_enqueue_lease_ack() -> None:
    queue = InMemoryTaskQueue()
    task = Task(task_type="daily_intelligence.run", payload={"topic": "AI"})

    queue.enqueue(task)
    leased = queue.lease("worker-1", ["news:queue:daily"])
    queue.ack(leased.task_id, "worker-1")

    assert leased is task
    assert leased.status == TaskStatus.LEASED
    assert queue.lease("worker-1", ["news:queue:daily"]) is None


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
