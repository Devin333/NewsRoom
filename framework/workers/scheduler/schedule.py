from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.workers.models.task import DEFAULT_TASK_QUEUE, Task
from framework.workers.scheduler.misfire import MisfirePolicy
from framework.workers.scheduler.trigger import ScheduleTriggerType


@dataclass
class ScheduleSpec:
    schedule_id: str
    name: str
    trigger_type: ScheduleTriggerType | str
    task_type: str
    payload_template: dict[str, Any] = field(default_factory=dict)
    queue_name: str = DEFAULT_TASK_QUEUE
    enabled: bool = True
    timezone: str = "Asia/Tokyo"
    interval_seconds: int | None = None
    run_at: datetime | None = None
    cron: str | None = None
    misfire_policy: MisfirePolicy | str = MisfirePolicy.RUN_ONCE
    max_catchup_runs: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.trigger_type = ScheduleTriggerType(self.trigger_type)
        self.misfire_policy = MisfirePolicy(self.misfire_policy)
        self.run_at = ensure_utc(self.run_at) if self.run_at is not None else None
        self.payload_template = dict(self.payload_template)
        self.metadata = dict(self.metadata)
        if not self.schedule_id:
            raise ValueError("schedule_id is required")
        if not self.name:
            raise ValueError("name is required")
        if not self.task_type:
            raise ValueError("task_type is required")
        if self.max_catchup_runs < 1:
            raise ValueError("max_catchup_runs must be greater than zero")
        if self.trigger_type == ScheduleTriggerType.INTERVAL:
            if self.interval_seconds is None or self.interval_seconds <= 0:
                raise ValueError("interval_seconds must be greater than zero")
        if self.trigger_type == ScheduleTriggerType.DATE and self.run_at is None:
            raise ValueError("run_at is required for date schedules")
        if self.trigger_type == ScheduleTriggerType.CRON and not self.cron:
            raise ValueError("cron is required for cron schedules")
        _reject_secret_payload_keys(self.payload_template)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "trigger_type": self.trigger_type.value,
            "trigger_config": {
                "cron": self.cron,
                "interval_seconds": self.interval_seconds,
                "run_at": format_datetime(self.run_at),
            },
            "task_type": self.task_type,
            "payload_template": dict(self.payload_template),
            "queue_name": self.queue_name,
            "enabled": self.enabled,
            "timezone": self.timezone,
            "misfire_policy": self.misfire_policy.value,
            "max_catchup_runs": self.max_catchup_runs,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleSpec":
        trigger_config = dict(data.get("trigger_config") or {})
        return cls(
            schedule_id=str(data["schedule_id"]),
            name=str(data["name"]),
            trigger_type=str(data["trigger_type"]),
            task_type=str(data["task_type"]),
            payload_template=dict(data.get("payload_template") or {}),
            queue_name=str(data.get("queue_name") or DEFAULT_TASK_QUEUE),
            enabled=bool(data.get("enabled", True)),
            timezone=str(data.get("timezone") or "Asia/Tokyo"),
            interval_seconds=trigger_config.get("interval_seconds"),
            run_at=parse_datetime(trigger_config.get("run_at")),
            cron=trigger_config.get("cron"),
            misfire_policy=str(data.get("misfire_policy") or MisfirePolicy.RUN_ONCE.value),
            max_catchup_runs=int(data.get("max_catchup_runs") or 1),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScheduleEvaluation:
    schedule_id: str
    trigger_type: ScheduleTriggerType
    due_times: tuple[datetime, ...] = ()
    next_run_at: datetime | None = None
    state_update_at: datetime | None = None
    enabled: bool = True
    reason: str | None = None

    @property
    def is_due(self) -> bool:
        return bool(self.due_times)


@dataclass(frozen=True)
class EnqueuedScheduleTask:
    schedule_id: str
    due_at: datetime
    task: Task
    message_id: str | None = None


@dataclass(frozen=True)
class SchedulerTickResult:
    evaluations: tuple[ScheduleEvaluation, ...]
    enqueued: tuple[EnqueuedScheduleTask, ...]
    state_updates: dict[str, datetime]

    @property
    def enqueued_count(self) -> int:
        return len(self.enqueued)


def _reject_secret_payload_keys(payload: dict[str, Any]) -> None:
    secret_fragments = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    )
    for key in payload:
        normalized = str(key).lower().replace("-", "_")
        if any(fragment in normalized for fragment in secret_fragments):
            raise ValueError(f"schedule payload key is not allowed: {key}")
