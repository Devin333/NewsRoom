from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.framework.workers.models import Task
from core.framework.workers.redis_queue import RedisStreamTaskQueue
from core.framework.workers.schedule_store import ScheduleRecord, ScheduleStore
from core.framework.workers.scheduler import (
    EnqueuedScheduleTask,
    ScheduleEvaluation,
    Scheduler,
    SchedulerTickResult,
)
from storage.local_json import LocalJsonScheduleStore


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_SCHEDULE_STORE_PATH = ".newsroom/schedules/schedules.json"


@dataclass(frozen=True)
class ScheduleListResult:
    schedules: tuple[ScheduleRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_count": len(self.schedules),
            "schedules": [record.to_dict() for record in self.schedules],
        }


@dataclass(frozen=True)
class ScheduleUpsertResult:
    record: ScheduleRecord

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.record.schedule_id,
            "schedule": self.record.to_dict(),
        }


@dataclass(frozen=True)
class ScheduleServiceTickResult:
    tick: SchedulerTickResult
    updated_records: tuple[ScheduleRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_count": len(self.tick.evaluations),
            "enqueued_count": self.tick.enqueued_count,
            "evaluations": [_evaluation_to_dict(evaluation) for evaluation in self.tick.evaluations],
            "enqueued": [_enqueued_to_dict(item) for item in self.tick.enqueued],
            "state_updates": {
                schedule_id: _format_datetime(value)
                for schedule_id, value in self.tick.state_updates.items()
            },
            "updated_schedules": [record.to_dict() for record in self.updated_records],
        }


@dataclass(frozen=True)
class ManualScheduleTriggerResult:
    enqueued: EnqueuedScheduleTask
    updated_record: ScheduleRecord

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.enqueued.schedule_id,
            "enqueued": _enqueued_to_dict(self.enqueued),
            "updated_schedule": self.updated_record.to_dict(),
        }


class ScheduleApplicationService:
    def __init__(
        self,
        *,
        store: ScheduleStore | None = None,
        queue: Any | None = None,
        store_path: str | Path = DEFAULT_SCHEDULE_STORE_PATH,
        redis_url: str | None = None,
        now_fn: Any | None = None,
    ) -> None:
        self.store = store or LocalJsonScheduleStore(store_path)
        self.queue = queue or RedisStreamTaskQueue(_redis_client_from_url(redis_url))
        self.scheduler = Scheduler(self.queue, now_fn=now_fn)

    def list_schedules(self, *, enabled_only: bool = False) -> ScheduleListResult:
        return ScheduleListResult(tuple(self.store.list_schedules(enabled_only=enabled_only)))

    def upsert_schedule(self, record: ScheduleRecord) -> ScheduleUpsertResult:
        return ScheduleUpsertResult(self.store.upsert_schedule(record))

    def tick(
        self,
        *,
        now: datetime | None = None,
        enabled_only: bool = True,
    ) -> ScheduleServiceTickResult:
        records = self.store.list_schedules(enabled_only=enabled_only)
        last_run_at_by_schedule = {
            record.schedule_id: record.last_run_at
            for record in records
            if record.last_run_at is not None
        }
        tick_result = self.scheduler.enqueue_due(
            [record.spec for record in records],
            now=now,
            last_run_at_by_schedule=last_run_at_by_schedule,
        )
        evaluation_by_id = {evaluation.schedule_id: evaluation for evaluation in tick_result.evaluations}
        updated_records = []
        for schedule_id, last_run_at in tick_result.state_updates.items():
            evaluation = evaluation_by_id.get(schedule_id)
            updated_records.append(
                self.store.update_run_state(
                    schedule_id,
                    last_run_at=last_run_at,
                    next_run_at=evaluation.next_run_at if evaluation else None,
                )
            )
        return ScheduleServiceTickResult(tick=tick_result, updated_records=tuple(updated_records))

    def trigger_manual(
        self,
        schedule_id: str,
        *,
        now: datetime | None = None,
    ) -> ManualScheduleTriggerResult:
        record = self.store.get_schedule(schedule_id)
        enqueued = self.scheduler.trigger_manual(record.spec, now=now)
        updated = self.store.update_run_state(
            schedule_id,
            last_run_at=enqueued.due_at,
            next_run_at=None,
        )
        return ManualScheduleTriggerResult(enqueued=enqueued, updated_record=updated)


def _evaluation_to_dict(evaluation: ScheduleEvaluation) -> dict[str, Any]:
    return {
        "schedule_id": evaluation.schedule_id,
        "trigger_type": evaluation.trigger_type.value,
        "due_times": [_format_datetime(value) for value in evaluation.due_times],
        "next_run_at": _format_datetime(evaluation.next_run_at),
        "state_update_at": _format_datetime(evaluation.state_update_at),
        "enabled": evaluation.enabled,
        "reason": evaluation.reason,
        "is_due": evaluation.is_due,
    }


def _enqueued_to_dict(item: EnqueuedScheduleTask) -> dict[str, Any]:
    return {
        "schedule_id": item.schedule_id,
        "due_at": _format_datetime(item.due_at),
        "message_id": item.message_id,
        "task": _task_to_dict(item.task),
    }


def _task_to_dict(task: Task) -> dict[str, Any]:
    payload = task.to_dict()
    payload["status"] = task.status.value
    return payload


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _redis_client_from_url(redis_url: str | None):
    import redis

    url = redis_url or os.environ.get("NEWS_REDIS_URL", DEFAULT_REDIS_URL)
    return redis.from_url(url, decode_responses=True)
