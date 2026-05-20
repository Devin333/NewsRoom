from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.workers.models.status import WorkerStatus


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

    @property
    def queues(self) -> list[str]:
        return list(self.queue_names)

    def is_stale(self, *, now: datetime | None = None, stale_after_seconds: int = 60) -> bool:
        if stale_after_seconds < 0:
            return False
        if self.status in {WorkerStatus.STOPPING, WorkerStatus.STOPPED}:
            return False
        reference = ensure_utc(now) if now else datetime.now(UTC)
        return reference - ensure_utc(self.last_heartbeat_at) > timedelta(seconds=stale_after_seconds)

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
            "queues": list(self.queue_names),
            "status": self.status.value,
            "started_at": format_datetime(self.started_at),
            "last_heartbeat_at": format_datetime(self.last_heartbeat_at),
            "current_task_id": self.current_task_id,
            "processed_count": self.processed_count,
            "failed_count": self.failed_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerHeartbeat":
        return cls(
            worker_id=str(data["worker_id"]),
            queue_names=[
                str(queue_name)
                for queue_name in data.get("queue_names") or data.get("queues") or []
            ],
            status=WorkerStatus(data.get("status") or WorkerStatus.RUNNING.value),
            started_at=parse_datetime(data.get("started_at")) or datetime.now(UTC),
            last_heartbeat_at=parse_datetime(data.get("last_heartbeat_at")) or datetime.now(UTC),
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


class InMemoryWorkerHeartbeatStore:
    def __init__(self) -> None:
        self._records: dict[str, WorkerHeartbeat] = {}

    def save(self, record: WorkerHeartbeat) -> WorkerHeartbeat:
        self._records[record.worker_id] = record
        return record

    def heartbeat(self, record: WorkerHeartbeat) -> WorkerHeartbeat:
        return self.save(record)

    def get(self, worker_id: str) -> WorkerHeartbeat | None:
        return self._records.get(worker_id)

    def list(self) -> list[WorkerHeartbeat]:
        return [self._records[worker_id] for worker_id in sorted(self._records)]

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
        self._records.pop(worker_id, None)
