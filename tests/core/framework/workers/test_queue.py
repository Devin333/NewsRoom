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


class _FakeRedis:
    def __init__(self) -> None:
        self.xadd_calls = []

    def xadd(self, stream, payload):
        self.xadd_calls.append((stream, payload))
        return "1-0"
