from datetime import UTC, datetime, timedelta

import pytest

from core.framework.workers import (
    MisfirePolicy,
    ScheduleSpec,
    ScheduleTriggerType,
    Scheduler,
    TaskStatus,
)


def test_interval_schedule_requires_positive_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        ScheduleSpec(
            schedule_id="daily",
            name="Daily",
            trigger_type="interval",
            task_type="daily_intelligence.run",
            interval_seconds=0,
        )


def test_schedule_payload_rejects_secret_keys() -> None:
    with pytest.raises(ValueError, match="payload key"):
        ScheduleSpec(
            schedule_id="daily",
            name="Daily",
            trigger_type="manual",
            task_type="daily_intelligence.run",
            payload_template={"api_key": "do-not-store"},
        )


def test_disabled_schedule_is_skipped() -> None:
    scheduler = Scheduler(_FakeQueue())
    schedule = ScheduleSpec(
        schedule_id="daily",
        name="Daily",
        trigger_type=ScheduleTriggerType.INTERVAL,
        task_type="daily_intelligence.run",
        interval_seconds=3600,
        enabled=False,
    )

    evaluation = scheduler.evaluate(schedule, now=_dt("2026-05-11T00:00:00Z"))

    assert evaluation.is_due is False
    assert evaluation.enabled is False
    assert evaluation.reason == "disabled"


def test_date_schedule_is_due_once() -> None:
    scheduler = Scheduler(_FakeQueue())
    run_at = _dt("2026-05-11T09:00:00Z")
    schedule = ScheduleSpec(
        schedule_id="date-daily",
        name="Date daily",
        trigger_type="date",
        task_type="daily_intelligence.run",
        run_at=run_at,
    )

    due = scheduler.evaluate(schedule, now=_dt("2026-05-11T09:00:01Z"))
    already_run = scheduler.evaluate(schedule, now=_dt("2026-05-12T09:00:00Z"), last_run_at=run_at)

    assert due.due_times == (run_at,)
    assert due.state_update_at == run_at
    assert already_run.due_times == ()
    assert already_run.reason == "already_run"


def test_interval_schedule_run_once_uses_latest_missed_time() -> None:
    scheduler = Scheduler(_FakeQueue())
    last_run_at = _dt("2026-05-11T00:00:00Z")
    schedule = ScheduleSpec(
        schedule_id="daily",
        name="Daily",
        trigger_type="interval",
        task_type="daily_intelligence.run",
        interval_seconds=600,
        misfire_policy=MisfirePolicy.RUN_ONCE,
    )

    evaluation = scheduler.evaluate(
        schedule,
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at=last_run_at,
    )

    assert evaluation.due_times == (_dt("2026-05-11T00:30:00Z"),)
    assert evaluation.state_update_at == _dt("2026-05-11T00:30:00Z")
    assert evaluation.next_run_at == _dt("2026-05-11T00:40:00Z")


def test_interval_schedule_catch_up_caps_due_times() -> None:
    scheduler = Scheduler(_FakeQueue())
    schedule = ScheduleSpec(
        schedule_id="memory",
        name="Memory catchup",
        trigger_type="interval",
        task_type="memory_index",
        interval_seconds=600,
        misfire_policy="catch_up",
        max_catchup_runs=2,
    )

    evaluation = scheduler.evaluate(
        schedule,
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
    )

    assert evaluation.due_times == (
        _dt("2026-05-11T00:10:00Z"),
        _dt("2026-05-11T00:20:00Z"),
    )
    assert evaluation.state_update_at == _dt("2026-05-11T00:20:00Z")


def test_interval_schedule_catch_up_limited_alias_caps_due_times() -> None:
    scheduler = Scheduler(_FakeQueue())
    schedule = ScheduleSpec(
        schedule_id="memory",
        name="Memory catchup",
        trigger_type="interval",
        task_type="memory_index",
        interval_seconds=600,
        misfire_policy="catch_up_limited",
        max_catchup_runs=2,
    )

    evaluation = scheduler.evaluate(
        schedule,
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
    )

    assert schedule.misfire_policy == MisfirePolicy.CATCH_UP_LIMITED
    assert evaluation.due_times == (
        _dt("2026-05-11T00:10:00Z"),
        _dt("2026-05-11T00:20:00Z"),
    )


def test_interval_schedule_skip_advances_state_without_enqueue() -> None:
    queue = _FakeQueue()
    scheduler = Scheduler(queue)
    schedule = ScheduleSpec(
        schedule_id="source-health",
        name="Source health",
        trigger_type="interval",
        task_type="source_health_check",
        interval_seconds=600,
        misfire_policy="skip",
    )

    result = scheduler.enqueue_due(
        [schedule],
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at_by_schedule={"source-health": _dt("2026-05-11T00:00:00Z")},
    )

    assert result.enqueued_count == 0
    assert result.state_updates == {"source-health": _dt("2026-05-11T00:30:00Z")}
    assert queue.enqueued == []


def test_cron_schedule_is_due_on_matching_minute() -> None:
    scheduler = Scheduler(_FakeQueue())
    schedule = ScheduleSpec(
        schedule_id="cron-daily",
        name="Cron daily",
        trigger_type="cron",
        task_type="daily_intelligence.run",
        cron="15 9 * * *",
    )

    evaluation = scheduler.evaluate(schedule, now=_dt("2026-05-11T09:15:20Z"))

    assert evaluation.due_times == (_dt("2026-05-11T09:15:00Z"),)
    assert evaluation.next_run_at == _dt("2026-05-12T09:15:00Z")


def test_cron_schedule_catches_up_with_cap() -> None:
    scheduler = Scheduler(_FakeQueue())
    schedule = ScheduleSpec(
        schedule_id="cron-catchup",
        name="Cron catchup",
        trigger_type="cron",
        task_type="daily_intelligence.run",
        cron="*/10 * * * *",
        misfire_policy="catch_up",
        max_catchup_runs=2,
    )

    evaluation = scheduler.evaluate(
        schedule,
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at=_dt("2026-05-11T00:00:00Z"),
    )

    assert evaluation.due_times == (
        _dt("2026-05-11T00:20:00Z"),
        _dt("2026-05-11T00:30:00Z"),
    )


def test_scheduler_enqueues_due_interval_task_with_metadata() -> None:
    queue = _FakeQueue()
    scheduler = Scheduler(queue)
    schedule = ScheduleSpec(
        schedule_id="daily",
        name="Daily intelligence",
        trigger_type="interval",
        task_type="daily_intelligence.run",
        payload_template={"profile": "live-offline", "topic": "AI", "source_limit": 3},
        interval_seconds=3600,
        metadata={"owner": "scheduler"},
    )

    result = scheduler.enqueue_due(
        [schedule],
        now=_dt("2026-05-11T01:00:00Z"),
        last_run_at_by_schedule={"daily": _dt("2026-05-11T00:00:00Z")},
    )

    assert result.enqueued_count == 1
    assert result.state_updates == {"daily": _dt("2026-05-11T01:00:00Z")}
    enqueued = result.enqueued[0]
    assert enqueued.message_id == "msg-1"
    assert enqueued.task.status == TaskStatus.QUEUED
    assert enqueued.task.scheduled_for == _dt("2026-05-11T01:00:00Z")
    assert enqueued.task.metadata == {
        "owner": "scheduler",
        "schedule_id": "daily",
        "schedule_name": "Daily intelligence",
        "schedule_trigger_type": "interval",
        "schedule_due_at": "2026-05-11T01:00:00Z",
    }
    assert queue.enqueued == [enqueued.task]


def test_manual_schedule_requires_explicit_trigger() -> None:
    queue = _FakeQueue()
    scheduler = Scheduler(queue)
    schedule = ScheduleSpec(
        schedule_id="manual-daily",
        name="Manual daily",
        trigger_type="manual",
        task_type="daily_intelligence.run",
        payload_template={"topic": "AI"},
    )

    tick = scheduler.enqueue_due([schedule], now=_dt("2026-05-11T01:00:00Z"))
    manual = scheduler.trigger_manual(schedule, now=_dt("2026-05-11T01:05:00Z"))

    assert tick.enqueued_count == 0
    assert tick.evaluations[0].reason == "manual_trigger_required"
    assert manual.task.payload == {"topic": "AI"}
    assert manual.due_at == _dt("2026-05-11T01:05:00Z")
    assert queue.enqueued == [manual.task]


def test_scheduler_enqueues_catch_up_task_metadata_with_original_due_time() -> None:
    queue = _FakeQueue()
    scheduler = Scheduler(queue)
    schedule = ScheduleSpec(
        schedule_id="memory",
        name="Memory catchup",
        trigger_type="interval",
        task_type="memory.reindex",
        payload_template={"run_id": "run-1"},
        interval_seconds=600,
        misfire_policy="catch_up",
        max_catchup_runs=2,
    )

    result = scheduler.enqueue_due(
        [schedule],
        now=_dt("2026-05-11T00:35:00Z"),
        last_run_at_by_schedule={"memory": _dt("2026-05-11T00:00:00Z")},
    )

    assert result.enqueued_count == 2
    assert result.enqueued[0].task.metadata["schedule_due_at"] == "2026-05-11T00:10:00Z"
    assert result.enqueued[1].task.metadata["schedule_due_at"] == "2026-05-11T00:20:00Z"


def test_task_serialization_preserves_schedule_metadata() -> None:
    queue = _FakeQueue()
    scheduler = Scheduler(queue)
    schedule = ScheduleSpec(
        schedule_id="manual-daily",
        name="Manual daily",
        trigger_type="manual",
        task_type="daily_intelligence.run",
    )

    enqueued = scheduler.trigger_manual(schedule, now=_dt("2026-05-11T01:05:00Z"))
    round_tripped = enqueued.task.from_dict(enqueued.task.to_dict())

    assert round_tripped.scheduled_for == _dt("2026-05-11T01:05:00Z")
    assert round_tripped.metadata["schedule_id"] == "manual-daily"


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, task):
        task.status = TaskStatus.QUEUED
        self.enqueued.append(task)
        return f"msg-{len(self.enqueued)}"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
