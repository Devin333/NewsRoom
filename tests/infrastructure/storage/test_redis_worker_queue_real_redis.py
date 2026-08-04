from __future__ import annotations

import os
from uuid import uuid4

import pytest

from framework.workers import StaleTaskLeaseError, Task
from infrastructure.storage.workers.redis_queue import RedisStreamTaskQueue


REDIS_URL = os.environ.get("NEWS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason="set NEWS_TEST_REDIS_URL to run real Redis worker lease coverage",
)


def test_real_redis_active_renewal_reclaim_and_late_completion() -> None:
    import redis

    client = redis.from_url(REDIS_URL, decode_responses=True)
    suffix = uuid4().hex
    queue_name = f"news:test:worker:{suffix}"
    queue = RedisStreamTaskQueue(
        client,
        group_name=f"news-test-workers-{suffix}",
        dead_letter_queue_name=f"{queue_name}:dlq",
        lease_ttl_ms=250,
        lease_key_prefix=f"news:test:worker-leases:{suffix}",
    )
    try:
        queue.enqueue(Task(task_type="test", payload={}, queue_name=queue_name, task_id=suffix))
        first = queue.lease_one("worker-a", [queue_name], block_ms=1)
        assert first is not None
        queue.renew(first)
        assert queue.reclaim_stale_one("worker-b", [queue_name], min_idle_ms=0) is None

        import time

        time.sleep(0.3)
        second = queue.reclaim_stale_one("worker-b", [queue_name], min_idle_ms=0)
        assert second is not None
        assert second.attempt == 2
        assert second.fencing_token == 2
        with pytest.raises(StaleTaskLeaseError):
            queue.ack(first)
        assert queue.ack(second) == 1
    finally:
        for key in client.scan_iter(match=f"*{suffix}*"):
            client.delete(key)
