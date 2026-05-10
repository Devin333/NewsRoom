from __future__ import annotations

import json
from typing import Any

from core.framework.workers.models import LeasedTask, Task, TaskStatus


class RedisStreamTaskQueue:
    def __init__(self, redis_client: Any, *, group_name: str = "news-workers") -> None:
        self.redis = redis_client
        self.group_name = group_name

    def enqueue(self, task: Task) -> str:
        task.status = TaskStatus.QUEUED
        task.leased_by = None
        return self.redis.xadd(
            task.queue_name,
            {"task": json.dumps(task.to_dict(), ensure_ascii=False, sort_keys=True)},
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
                raw_task = _field_value(fields, "task")
                task = Task.from_dict(json.loads(_decode(raw_task)))
                task.status = TaskStatus.LEASED
                task.leased_by = worker_id
                task.attempts += 1
                return LeasedTask(
                    queue_name=decoded_queue_name,
                    message_id=_decode(message_id),
                    task=task,
                )
        return None

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
