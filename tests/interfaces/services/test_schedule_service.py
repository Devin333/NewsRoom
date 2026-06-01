from datetime import UTC, datetime

from framework.workers import (
    InMemoryScheduleStore,
    ScheduleRecord,
    ScheduleSpec,
    TaskStatus,
)
from interfaces.services.schedule_service import ScheduleApplicationService


def test_schedule_service_lists_enabled_schedules() -> None:
    service = ScheduleApplicationService(
        store=InMemoryScheduleStore([_record("daily"), _record("disabled", enabled=False)]),
        queue=_FakeQueue(),
    )

    result = service.list_schedules(enabled_only=True)

    assert result.to_dict()["schedule_count"] == 1
    assert result.schedules[0].schedule_id == "daily"


def test_schedule_service_upserts_schedule_record() -> None:
    store = InMemoryScheduleStore()
    service = ScheduleApplicationService(store=store, queue=_FakeQueue())
    record = _record("daily")

    result = service.upsert_schedule(record)

    assert result.to_dict()["schedule_id"] == "daily"
    assert store.get_schedule("daily").schedule_id == "daily"


def test_schedule_service_upserts_daily_schedule_from_application_args() -> None:
    store = InMemoryScheduleStore()
    service = ScheduleApplicationService(store=store, queue=_FakeQueue())

    result = service.upsert_daily_schedule(
        schedule_id="daily",
        trigger_type="interval",
        interval_seconds=3600,
        run_at=_dt("2026-05-11T00:00:00Z"),
        profile="live-offline",
        topic="AI policy",
        source_limit=2,
        queue_name="news:queue:custom",
    )

    record = store.get_schedule("daily")
    assert result.to_dict()["schedule_id"] == "daily"
    assert record.spec.trigger_type.value == "interval"
    assert record.spec.interval_seconds == 3600
    assert record.spec.run_at == _dt("2026-05-11T00:00:00Z")
    assert record.spec.queue_name == "news:queue:custom"
    assert record.spec.payload_template == {
        "profile": "live-offline",
        "topic": "AI policy",
        "source_limit": 2,
    }


def test_schedule_service_upserts_paper_ingest_schedule_from_application_args() -> None:
    store = InMemoryScheduleStore()
    service = ScheduleApplicationService(store=store, queue=_FakeQueue())

    result = service.upsert_paper_ingest_schedule(
        schedule_id="papers",
        trigger_type="interval",
        interval_seconds=86400,
        candidate_limit=100,
        min_github_stars=50,
        queue_name="news:queue:papers",
    )

    record = store.get_schedule("papers")
    assert result.to_dict()["schedule_id"] == "papers"
    assert record.spec.task_type == "papers.ingest_github_arxiv_daily"
    assert record.spec.queue_name == "news:queue:papers"
    assert record.spec.payload_template == {
        "candidate_limit": 100,
        "min_github_stars": 50,
    }


def test_schedule_service_upserts_paper_reader_backfill_schedule_from_application_args() -> None:
    store = InMemoryScheduleStore()
    service = ScheduleApplicationService(store=store, queue=_FakeQueue())

    result = service.upsert_paper_visual_compile_backfill_schedule(
        schedule_id="paper-reader-backfill",
        trigger_type="interval",
        interval_seconds=21600,
        limit=50,
        force=True,
        queue_name="news:queue:papers",
    )

    record = store.get_schedule("paper-reader-backfill")
    assert result.to_dict()["schedule_id"] == "paper-reader-backfill"
    assert record.spec.task_type == "papers.visual_compile_backfill"
    assert record.spec.queue_name == "news:queue:papers"
    assert record.spec.payload_template == {
        "force": True,
        "limit": 50,
    }


def test_schedule_service_tick_enqueues_due_schedule_and_updates_state() -> None:
    store = InMemoryScheduleStore(
        [
            _record(
                "daily",
                last_run_at=_dt("2026-05-11T00:00:00Z"),
                interval_seconds=3600,
            )
        ]
    )
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.tick(now=_dt("2026-05-11T01:00:00Z"))

    payload = result.to_dict()
    assert payload["enqueued_count"] == 1
    assert payload["state_updates"] == {"daily": "2026-05-11T01:00:00Z"}
    assert store.get_schedule("daily").last_run_at == _dt("2026-05-11T01:00:00Z")
    assert store.get_schedule("daily").next_run_at == _dt("2026-05-11T02:00:00Z")
    assert queue.enqueued[0].metadata["schedule_id"] == "daily"
    assert queue.enqueued[0].status == TaskStatus.QUEUED


def test_schedule_service_tick_persists_skipped_misfire_state() -> None:
    store = InMemoryScheduleStore(
        [
            _record(
                "source-health",
                last_run_at=_dt("2026-05-11T00:00:00Z"),
                interval_seconds=600,
                misfire_policy="skip",
            )
        ]
    )
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.tick(now=_dt("2026-05-11T00:35:00Z"))

    payload = result.to_dict()
    assert payload["enqueued_count"] == 0
    assert payload["evaluations"][0]["reason"] == "misfire_skipped"
    assert store.get_schedule("source-health").last_run_at == _dt("2026-05-11T00:30:00Z")
    assert store.get_schedule("source-health").next_run_at == _dt("2026-05-11T00:40:00Z")
    assert queue.enqueued == []


def test_schedule_service_manual_trigger_enqueues_and_updates_state() -> None:
    store = InMemoryScheduleStore([_manual_record("manual-daily")])
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.trigger_manual("manual-daily", now=_dt("2026-05-11T01:05:00Z"))

    payload = result.to_dict()
    assert payload["schedule_id"] == "manual-daily"
    assert payload["enqueued"]["message_id"] == "msg-1"
    assert store.get_schedule("manual-daily").last_run_at == _dt("2026-05-11T01:05:00Z")
    assert queue.enqueued[0].payload == {"topic": "AI"}


def test_schedule_service_run_loop_stops_after_max_ticks() -> None:
    store = InMemoryScheduleStore(
        [
            _record(
                "daily",
                last_run_at=_dt("2026-05-11T00:00:00Z"),
                interval_seconds=3600,
            )
        ]
    )
    queue = _FakeQueue()
    service = ScheduleApplicationService(store=store, queue=queue)

    result = service.run_loop(
        now=_dt("2026-05-11T01:00:00Z"),
        max_ticks=2,
        tick_interval_seconds=0,
    )

    payload = result.to_dict()
    assert payload["stop_reason"] == "max_ticks"
    assert payload["tick_count"] == 2
    assert payload["enqueued_count"] == 1
    assert payload["idle_tick_count"] == 1


def test_schedule_service_run_loop_stops_after_idle_ticks() -> None:
    service = ScheduleApplicationService(store=InMemoryScheduleStore(), queue=_FakeQueue())

    result = service.run_loop(max_idle_ticks=2, tick_interval_seconds=0)

    payload = result.to_dict()
    assert payload["stop_reason"] == "max_idle_ticks"
    assert payload["tick_count"] == 2
    assert payload["enqueued_count"] == 0
    assert payload["idle_tick_count"] == 2


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, task):
        task.status = TaskStatus.QUEUED
        self.enqueued.append(task)
        return f"msg-{len(self.enqueued)}"


def _record(
    schedule_id: str,
    *,
    enabled: bool = True,
    last_run_at=None,
    interval_seconds: int = 3600,
    misfire_policy: str = "run_once",
) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="interval",
            task_type="daily_intelligence.run",
            payload_template={"topic": "AI"},
            interval_seconds=interval_seconds,
            enabled=enabled,
            misfire_policy=misfire_policy,
        ),
        last_run_at=last_run_at,
    )


def _manual_record(schedule_id: str) -> ScheduleRecord:
    return ScheduleRecord(
        spec=ScheduleSpec(
            schedule_id=schedule_id,
            name=schedule_id.title(),
            trigger_type="manual",
            task_type="daily_intelligence.run",
            payload_template={"topic": "AI"},
        )
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
