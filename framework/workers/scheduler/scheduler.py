from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from framework.shared.time import ensure_utc
from framework.workers.models.task import Task
from framework.workers.scheduler.misfire import MisfirePolicy
from framework.workers.scheduler.schedule import (
    EnqueuedScheduleTask,
    ScheduleEvaluation,
    ScheduleSpec,
    SchedulerTickResult,
)
from framework.workers.scheduler.trigger import ScheduleTriggerType


class TaskQueueWriter(Protocol):
    def enqueue(self, task: Task) -> Any: ...


class Scheduler:
    def __init__(
        self,
        queue: TaskQueueWriter,
        *,
        now_fn: Callable[[], datetime] | None = None,
        max_cron_catchup_minutes: int = 1440,
    ) -> None:
        self.queue = queue
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        if max_cron_catchup_minutes < 1:
            raise ValueError("max_cron_catchup_minutes must be greater than zero")
        self.max_cron_catchup_minutes = max_cron_catchup_minutes

    def tick(
        self,
        schedules: Iterable[ScheduleSpec],
        *,
        now: datetime | None = None,
        last_run_at_by_schedule: dict[str, datetime] | None = None,
    ) -> SchedulerTickResult:
        return self.enqueue_due(
            schedules,
            now=now,
            last_run_at_by_schedule=last_run_at_by_schedule,
        )

    def evaluate(
        self,
        schedule: ScheduleSpec,
        *,
        now: datetime | None = None,
        last_run_at: datetime | None = None,
    ) -> ScheduleEvaluation:
        current = ensure_utc(now or self.now_fn())
        last = ensure_utc(last_run_at) if last_run_at is not None else None

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
        current = ensure_utc(now or self.now_fn())
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
        return self._enqueue_schedule_task(schedule, ensure_utc(now or self.now_fn()))

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
        scanned_minutes = _minute_range(start, current_minute, max_minutes=self.max_cron_catchup_minutes)
        catchup_bounded = (current_minute - start) > timedelta(minutes=self.max_cron_catchup_minutes - 1)
        due_times = [moment for moment in scanned_minutes if _cron_matches(schedule.cron, moment)]
        if not due_times:
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, current_minute),
                reason="catchup_bounded" if catchup_bounded else "not_due",
            )
        if len(due_times) > 1 and schedule.misfire_policy == MisfirePolicy.SKIP:
            latest = due_times[-1]
            return ScheduleEvaluation(
                schedule_id=schedule.schedule_id,
                trigger_type=schedule.trigger_type,
                next_run_at=_next_cron_time(schedule.cron, latest),
                state_update_at=latest,
                reason="catchup_bounded_skipped" if catchup_bounded else "misfire_skipped",
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
            reason="catchup_bounded" if catchup_bounded else None,
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
