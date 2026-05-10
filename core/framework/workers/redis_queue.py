from __future__ import annotations

import json
from typing import Any

from core.framework.workers.models import Task, TaskStatus


class RedisStreamTaskQueue:
    def __init__(self, redis_client: Any, *, group_name: str = "news-workers") -> None:
        self.redis = redis_client
        self.group_name = group_name

    def enqueue(self, task: Task) -> str:
        task.status = TaskStatus.QUEUED
        return self.redis.xadd(
            task.queue_name,
            {"task": json.dumps(task.to_dict(), ensure_ascii=False, sort_keys=True)},
        )

    def lease(self, worker_id: str, queue_names: list[str], *, count: int = 1, block_ms: int = 1000):
        streams = {queue_name: ">" for queue_name in queue_names}
        return self.redis.xreadgroup(self.group_name, worker_id, streams, count=count, block=block_ms)

    def ack(self, queue_name: str, message_id: str) -> int:
        return self.redis.xack(queue_name, self.group_name, message_id)

    def move_to_dead_letter(self, task: Task, reason: str) -> str:
        task.status = TaskStatus.DEAD_LETTER
        payload = task.to_dict()
        payload["dead_letter_reason"] = reason
        return self.redis.xadd(
            "news:queue:dead-letter",
            {"task": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
        )
