from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any


class WorkerStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    queue_names: list[str]
    status: WorkerStatus = WorkerStatus.RUNNING
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_task_id: str | None = None
    processed_count: int = 0
    failed_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_stale(self, *, now: datetime | None = None, stale_after_seconds: int = 60) -> bool:
        if stale_after_seconds < 0:
            return False
        if self.status in {WorkerStatus.STOPPING, WorkerStatus.STOPPED}:
            return False
        reference = _coerce_datetime(now) if now else datetime.now(UTC)
        heartbeat_at = _coerce_datetime(self.last_heartbeat_at)
        return reference - heartbeat_at > timedelta(seconds=stale_after_seconds)

    def effective_status(
        self,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 60,
    ) -> WorkerStatus:
        if self.is_stale(now=now, stale_after_seconds=stale_after_seconds):
            return WorkerStatus.UNHEALTHY
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "queue_names": list(self.queue_names),
            "status": self.status.value,
            "started_at": _format_datetime(self.started_at),
            "last_heartbeat_at": _format_datetime(self.last_heartbeat_at),
            "current_task_id": self.current_task_id,
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerHeartbeat":
        return cls(
            worker_id=str(data["worker_id"]),
            queue_names=[str(queue_name) for queue_name in data.get("queue_names") or []],
            status=WorkerStatus(data.get("status") or WorkerStatus.RUNNING.value),
            started_at=_parse_datetime(data.get("started_at")),
            last_heartbeat_at=_parse_datetime(data.get("last_heartbeat_at")),
            current_task_id=data.get("current_task_id"),
            processed_count=int(data.get("processed_count") or 0),
            failed_count=int(data.get("failed_count") or 0),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkerHeartbeatStatus:
    record: WorkerHeartbeat
    status: WorkerStatus
    stale: bool

    @classmethod
    def from_record(
        cls,
        record: WorkerHeartbeat,
        *,
        now: datetime | None = None,
        stale_after_seconds: int = 60,
    ) -> "WorkerHeartbeatStatus":
        stale = record.is_stale(now=now, stale_after_seconds=stale_after_seconds)
        return cls(
            record=record,
            status=WorkerStatus.UNHEALTHY if stale else record.status,
            stale=stale,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.record.to_dict()
        payload["stored_status"] = self.record.status.value
        payload["status"] = self.status.value
        payload["stale"] = self.stale
        return payload


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

    def delete(self, worker_id: str) -> None:
        self.redis.delete(self._worker_key(worker_id))
        self.redis.srem(self.index_key, worker_id)

    def _worker_key(self, worker_id: str) -> str:
        return f"{self.key_prefix}:{worker_id}"


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _format_datetime(value: datetime) -> str:
    return _coerce_datetime(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _coerce_datetime(value)
    if isinstance(value, str) and value:
        return _coerce_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    return datetime.now(UTC)


def _coerce_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
