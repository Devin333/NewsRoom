from datetime import UTC, datetime, timedelta

from domain.sources import SourceError, SourceHealthStatus
from sources.health import BasicSourceHealthManager


def test_health_manager_records_success() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    manager = BasicSourceHealthManager(now=lambda: now)

    health = manager.record_success("source")

    assert health.status == SourceHealthStatus.HEALTHY
    assert health.consecutive_failures == 0
    assert health.last_success_at == now


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
    assert second.status == SourceHealthStatus.COOLING_DOWN
    assert second.cooldown_until == now + timedelta(seconds=60)
    assert manager.should_skip("source") is True


def test_health_manager_records_disabled_source_as_skipped() -> None:
    manager = BasicSourceHealthManager()

    health = manager.record_disabled("source", reason="manual disable")

    assert health.status == SourceHealthStatus.DISABLED
    assert health.last_error is not None
    assert health.last_error.error_type == "source_disabled"
    assert health.last_error.error_message == "manual disable"
    assert manager.should_skip("source") is True
