from datetime import UTC, datetime, timedelta

from domain.sources import SourceError, SourceHealth, SourceHealthStatus
from sources.health import BasicSourceHealthManager


class FakeHealthStore:
    def __init__(self, records: dict[str, SourceHealth] | None = None) -> None:
        self.records = dict(records or {})
        self.saved: list[SourceHealth] = []

    def get_source_health(self, source_id: str) -> SourceHealth | None:
        return self.records.get(source_id)

    def update_source_health(self, health: SourceHealth) -> None:
        self.records[health.source_id] = health
        self.saved.append(health)


def test_health_manager_records_success() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    manager = BasicSourceHealthManager(now=lambda: now)

    health = manager.record_success("source")

    assert health.status == SourceHealthStatus.HEALTHY
    assert health.consecutive_failures == 0
    assert health.success_count_24h == 1
    assert health.failure_count_24h == 0
    assert health.avg_latency_ms_24h is None
    assert health.last_success_at == now


def test_health_manager_records_and_updates_source_context() -> None:
    manager = BasicSourceHealthManager()

    health = manager.record_success(
        "source",
        source_name="Source Name",
        url="https://example.com/rss",
    )
    contextual = manager.get(
        "source",
        source_name="Updated Source Name",
        url="https://example.com/updated",
    )

    assert health.source_name == "Source Name"
    assert health.url == "https://example.com/rss"
    assert contextual.source_name == "Updated Source Name"
    assert contextual.url == "https://example.com/updated"
    assert contextual.success_count_24h == 1
    assert manager.get("source").source_name == "Updated Source Name"


def test_health_manager_opens_cooldown_after_failures() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    manager = BasicSourceHealthManager(
        failure_threshold=2,
        cooldown_seconds=60,
        now=lambda: now,
    )
    error = SourceError(source_id="source", error_type="fetch_timeout", error_message="timeout")

    first = manager.record_failure("source", error)
    second = manager.record_failure("source", error)

    assert first.status == SourceHealthStatus.DEGRADED
    assert first.failure_count_24h == 1
    assert second.status == SourceHealthStatus.COOLING_DOWN
    assert second.failure_count_24h == 2
    assert second.cooldown_until == now + timedelta(seconds=60)
    assert manager.should_skip("source") is True


def test_health_manager_computes_rolling_24h_counts_and_latency() -> None:
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    manager = BasicSourceHealthManager(now=lambda: clock["now"])
    error = SourceError(source_id="source", error_type="fetch_timeout", error_message="timeout")

    success = manager.record_success("source", latency_ms=10)
    clock["now"] = clock["now"] + timedelta(hours=1)
    failure = manager.record_failure("source", error, latency_ms=30)

    assert success.success_count_24h == 1
    assert success.avg_latency_ms_24h == 10.0
    assert failure.success_count_24h == 1
    assert failure.failure_count_24h == 1
    assert failure.avg_latency_ms_24h == 20.0

    clock["now"] = clock["now"] + timedelta(hours=25)
    refreshed = manager.get("source")

    assert refreshed.success_count_24h == 0
    assert refreshed.failure_count_24h == 0
    assert refreshed.avg_latency_ms_24h is None


def test_health_manager_marks_expired_cooldown_as_probe_ready() -> None:
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=60,
        now=lambda: clock["now"],
    )
    error = SourceError(source_id="source", error_type="fetch_timeout", error_message="timeout")

    manager.record_failure("source", error)

    assert manager.should_skip("source") is True
    assert manager.should_fetch("source") is False
    assert manager.should_probe("source") is False

    clock["now"] = clock["now"] + timedelta(seconds=61)

    assert manager.should_skip("source") is False
    assert manager.should_fetch("source") is True
    assert manager.should_probe("source") is True


def test_health_manager_uses_error_context_on_failure() -> None:
    manager = BasicSourceHealthManager()
    error = SourceError(
        source_id="source",
        source_name="Source Name",
        error_type="fetch_timeout",
        error_message="timeout",
        url="https://example.com/rss",
    )

    health = manager.record_failure("source", error)

    assert health.source_name == "Source Name"
    assert health.url == "https://example.com/rss"


def test_health_manager_records_disabled_source_as_skipped() -> None:
    manager = BasicSourceHealthManager()

    health = manager.record_disabled(
        "source",
        reason="manual disable",
        source_name="Source Name",
        url="https://example.com/rss",
    )

    assert health.status == SourceHealthStatus.DISABLED
    assert health.source_name == "Source Name"
    assert health.url == "https://example.com/rss"
    assert health.last_error is not None
    assert health.last_error.source_name == "Source Name"
    assert health.last_error.url == "https://example.com/rss"
    assert health.last_error.error_type == "source_disabled"
    assert health.last_error.error_message == "manual disable"
    assert manager.should_skip("source") is True


def test_health_manager_hydrates_from_store_before_skip_decision() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    store = FakeHealthStore(
        {
            "source": SourceHealth(
                source_id="source",
                status=SourceHealthStatus.COOLING_DOWN,
                consecutive_failures=2,
                cooldown_until=now + timedelta(minutes=5),
                source_name="Stored Source",
                url="https://example.com/rss",
            )
        }
    )
    manager = BasicSourceHealthManager(now=lambda: now, health_store=store)

    health = manager.get("source")

    assert health.status == SourceHealthStatus.COOLING_DOWN
    assert health.source_name == "Stored Source"
    assert manager.should_skip("source") is True


def test_health_manager_persists_mutated_health_to_store() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    store = FakeHealthStore()
    manager = BasicSourceHealthManager(now=lambda: now, health_store=store)

    health = manager.record_success(
        "source",
        latency_ms=25,
        source_name="Source Name",
        url="https://example.com/rss",
    )

    assert store.saved == [health]
    assert store.records["source"].status == SourceHealthStatus.HEALTHY
    assert store.records["source"].source_name == "Source Name"


def test_health_manager_merges_persisted_window_counts_on_first_event() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    store = FakeHealthStore(
        {
            "source": SourceHealth(
                source_id="source",
                status=SourceHealthStatus.DEGRADED,
                consecutive_failures=1,
                success_count_24h=2,
                failure_count_24h=1,
                avg_latency_ms_24h=30,
                last_success_at=now - timedelta(hours=1),
                last_failure_at=now - timedelta(minutes=30),
            )
        }
    )
    manager = BasicSourceHealthManager(now=lambda: now, health_store=store)

    health = manager.record_success("source", latency_ms=60)

    assert health.success_count_24h == 3
    assert health.failure_count_24h == 1
    assert health.avg_latency_ms_24h == 37.5
