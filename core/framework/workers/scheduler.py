from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Protocol

from core.framework.workers.models import Task


class ScheduleTriggerType(str, Enum):
    MANUAL = "manual"
    DATE = "date"
    INTERVAL = "interval"
    CRON = "cron"
    EVENT = "event"
    WEBHOOK = "webhook"
    SOURCE_HEALTH = "source_health"
    SUBSCRIPTION = "subscription"


class MisfirePolicy(str, Enum):
    SKIP = "skip"
    RUN_ONCE = "run_once"
    CATCH_UP = "catch_up"


class TaskQueueWriter(Protocol):
    def enqueue(self, task: Task) -> Any: ...


@dataclass
class ScheduleSpec:
    schedule_id: str
    name: str
    trigger_type: ScheduleTriggerType | str
    task_type: str
    payload_template: dict[str, Any] = field(default_factory=dict)
    queue_name: str = "news:queue:daily"
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
        self.run_at = _normalize_datetime(self.run_at)
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
                "run_at": _format_datetime(self.run_at),
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
    def from_dict(cls, data: dict[str, Any]) -> ScheduleSpec:
        trigger_config = dict(data.get("trigger_config") or {})
        return cls(
            schedule_id=str(data["schedule_id"]),
            name=str(data["name"]),
            trigger_type=str(data["trigger_type"]),
            task_type=str(data["task_type"]),
            payload_template=dict(data.get("payload_template") or {}),
            queue_name=str(data.get("queue_name") or "news:queue:daily"),
            enabled=bool(data.get("enabled", True)),
            timezone=str(data.get("timezone") or "Asia/Tokyo"),
            interval_seconds=trigger_config.get("interval_seconds"),
            run_at=_parse_optional_datetime(trigger_config.get("run_at")),
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


class Scheduler:
    def __init__(
        self,
        queue: TaskQueueWriter,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.queue = queue
        self.now_fn = now_fn or (lambda: datetime.now(UTC))

    def evaluate(
        self,
        schedule: ScheduleSpec,
        *,
        now: datetime | None = None,
        last_run_at: datetime | None = None,
    ) -> ScheduleEvaluation:
        current = _normalize_datetime(now or self.now_fn())
        last = _normalize_datetime(last_run_at)

        if not schedule.enabled:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                enabled=False,
                reason="disabled",
            )
        if schedule.trigger_type == ScheduleTriggerType.MANUAL:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                reason="manual_trigger_required",
            )
        if schedule.trigger_type == ScheduleTriggerType.DATE:
            return self._evaluate_date(schedule, current, last)
        if schedule.trigger_type == ScheduleTriggerType.INTERVAL:
            return self._evaluate_interval(schedule, current, last)
        if schedule.trigger_type == ScheduleTriggerType.CRON:
            return self._evaluate_cron(schedule, current, last)
        return ScheduleEvaluation(
            schedule_id=schedule.schedule_id,
            trigger_type=schedule.trigger_type,
            reason="unsupported_trigger",
        )

    def enqueue_due(
        self,
        schedules: Iterable[ScheduleSpec],
        *,
        now: datetime | None = None,
        last_run_at_by_schedule: dict[str, datetime] | None = None,
    ) -> SchedulerTickResult:
        current = _normalize_datetime(now or self.now_fn())
        state = last_run_at_by_schedule or {}
        evaluations: list[ScheduleEvaluation] = []
        enqueued: list[EnqueuedScheduleTask] = []
        state_updates: dict[str, datetime] = {}

        for schedule in schedules:
            evaluation = self.evaluate(
                schedule,
                now=current,
                last_run_at=state.get(schedule.schedule_id),
            )
            evaluations.append(evaluation)
            for due_at in evaluation.due_times:
                enqueued_task = self._enqueue_schedule_task(schedule, due_at)
                enqueued.append(enqueued_task)
                state_updates[schedule.schedule_id] = due_at
            if not evaluation.due_times and evaluation.state_update_at is not None:
                state_updates[schedule.schedule_id] = evaluation.state_update_at

        return SchedulerTickResult(
            evaluations=tuple(evaluations),
            enqueued=tuple(enqueued),
            state_updates=state_updates,
        )

    def trigger_manual(
        self,
        schedule: ScheduleSpec,
        *,
        now: datetime | None = None,
    ) -> EnqueuedScheduleTask:
        if not schedule.enabled:
            raise ValueError(f"schedule is disabled: {schedule.schedule_id}")
        if schedule.trigger_type != ScheduleTriggerType.MANUAL:
            raise ValueError(f"schedule is not manual: {schedule.schedule_id}")
        return self._enqueue_schedule_task(schedule, _normalize_datetime(now or self.now_fn()))

    def _evaluate_date(
        self,
        schedule: ScheduleSpec,
        now: datetime,
        last_run_at: datetime | None,
    ) -> ScheduleEvaluation:
        run_at = schedule.run_at
        if run_at is None:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                reason="missing_run_at",
            )
        if last_run_at is not None:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                reason="already_run",
            )
        if now < run_at:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=run_at,
                reason="not_due",
            )
        return ScheduleEvaluation(
            schedule_id=schedule.schedule_id,
            trigger_type=schedule.trigger_type,
            due_times=(run_at,),
            state_update_at=run_at,
        )

    def _evaluate_interval(
        self,
        schedule: ScheduleSpec,
        now: datetime,
        last_run_at: datetime | None,
    ) -> ScheduleEvaluation:
        interval = timedelta(seconds=schedule.interval_seconds or 0)
        first_due_at = schedule.run_at or now
        base_due_at = first_due_at if last_run_at is None else last_run_at + interval

        if now < base_due_at:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=base_due_at,
                reason="not_due",
            )

        due_count = _interval_due_count(base_due_at, now, interval)
        latest_due_at = base_due_at + (due_count - 1) * interval

        if due_count > 1 and schedule.misfire_policy == MisfirePolicy.SKIP:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=latest_due_at + interval,
                state_update_at=latest_due_at,
                reason="misfire_skipped",
            )

        due_times = _interval_due_times(
            base_due_at=base_due_at,
            interval=interval,
            due_count=due_count,
            policy=schedule.misfire_policy,
            max_catchup_runs=schedule.max_catchup_runs,
        )
        return ScheduleEvaluation(
            schedule_id=schedule.schedule_id,
            trigger_type=schedule.trigger_type,
            due_times=due_times,
            next_run_at=due_times[-1] + interval,
            state_update_at=due_times[-1],
        )

    def _evaluate_cron(
        self,
        schedule: ScheduleSpec,
        now: datetime,
        last_run_at: datetime | None,
    ) -> ScheduleEvaluation:
        if not schedule.cron:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                reason="missing_cron",
            )
        current_minute = now.replace(second=0, microsecond=0)
        if last_run_at is None:
            if _cron_matches(schedule.cron, current_minute):
                return ScheduleEvaluation(
                    schedule_id=schedule.schedule_id,
                    trigger_type=schedule.trigger_type,
                    due_times=(current_minute,),
                    state_update_at=current_minute,
                    next_run_at=_next_cron_time(schedule.cron, current_minute),
                )
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, current_minute),
                reason="not_due",
            )

        start = last_run_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
        if start > current_minute:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, current_minute),
                reason="not_due",
            )
        due_times = [
            moment
            for moment in _minute_range(start, current_minute, max_minutes=1440)
            if _cron_matches(schedule.cron, moment)
        ]
        if not due_times:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, current_minute),
                reason="not_due",
            )
        if len(due_times) > 1 and schedule.misfire_policy == MisfirePolicy.SKIP:
            latest = due_times[-1]
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, latest),
                state_update_at=latest,
                reason="misfire_skipped",
            )
        if schedule.misfire_policy == MisfirePolicy.RUN_ONCE:
            due_times = [due_times[-1]]
        elif len(due_times) > schedule.max_catchup_runs:
            due_times = due_times[-schedule.max_catchup_runs :]
        return ScheduleEvaluation(
            schedule_id=schedule.schedule_id,
            trigger_type=schedule.trigger_type,
            due_times=tuple(due_times),
            state_update_at=due_times[-1],
            next_run_at=_next_cron_time(schedule.cron, due_times[-1]),
        )

    def _enqueue_schedule_task(self, schedule: ScheduleSpec, due_at: datetime) -> EnqueuedScheduleTask:
        task = Task(
            task_type=schedule.task_type,
            payload=dict(schedule.payload_template),
            queue_name=schedule.queue_name,
            scheduled_for=due_at,
            metadata={
                **schedule.metadata,
                "schedule_id": schedule.schedule_id,
                "schedule_name": schedule.name,
                "schedule_trigger_type": schedule.trigger_type.value,
                "schedule_due_at": due_at.isoformat().replace("+00:00", "Z"),
            },
        )
        message_id = self.queue.enqueue(task)
        return EnqueuedScheduleTask(
            schedule_id=schedule.schedule_id,
            due_at=due_at,
            task=task,
            message_id=str(message_id) if message_id is not None else None,
        )


def _interval_due_count(base_due_at: datetime, now: datetime, interval: timedelta) -> int:
    elapsed_seconds = (now - base_due_at).total_seconds()
    return int(elapsed_seconds // interval.total_seconds()) + 1


def _interval_due_times(
    *,
    base_due_at: datetime,
    interval: timedelta,
    due_count: int,
    policy: MisfirePolicy,
    max_catchup_runs: int,
) -> tuple[datetime, ...]:
    if policy == MisfirePolicy.RUN_ONCE:
        return (base_due_at + (due_count - 1) * interval,)
    count = min(due_count, max_catchup_runs)
    return tuple(base_due_at + index * interval for index in range(count))


def _minute_range(start: datetime, end: datetime, *, max_minutes: int) -> tuple[datetime, ...]:
    minutes = []
    current = start
    while current <= end and len(minutes) < max_minutes:
        minutes.append(current)
        current += timedelta(minutes=1)
    return tuple(minutes)


def _next_cron_time(expression: str, after: datetime) -> datetime | None:
    current = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(1440):
        if _cron_matches(expression, current):
            return current
        current += timedelta(minutes=1)
    return None


def _cron_matches(expression: str, moment: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must have five fields")
    minute, hour, day, month, day_of_week = fields
    cron_weekday = (moment.weekday() + 1) % 7
    return (
        _field_matches(minute, moment.minute, 0, 59)
        and _field_matches(hour, moment.hour, 0, 23)
        and _field_matches(day, moment.day, 1, 31)
        and _field_matches(month, moment.month, 1, 12)
        and _field_matches(day_of_week, cron_weekday, 0, 7)
    )


def _field_matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be greater than zero")
            if (value - minimum) % step == 0:
                return True
            continue
        expected = int(part)
        if expected == 7 and maximum == 7:
            expected = 0
        if expected < minimum or expected > maximum:
            raise ValueError(f"cron field value out of range: {part}")
        if value == expected:
            return True
    return False


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if isinstance(value, str):
        return _normalize_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    raise TypeError(f"unsupported datetime value: {value!r}")


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
