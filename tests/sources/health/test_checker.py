from datetime import UTC, datetime, timedelta

from domain.sources import SourceDefinition, SourceError, SourceHealthStatus
from sources import SourceRegistry
from sources.health import BasicSourceHealthManager, ProbeObservation, SourceHealthChecker


def test_source_health_checker_probes_enabled_source_and_records_success() -> None:
    registry = SourceRegistry([_source()])
    manager = BasicSourceHealthManager(now=lambda: datetime(2026, 5, 11, tzinfo=UTC))

    result = SourceHealthChecker(
        registry,
        manager,
        probe_fetcher=lambda source, policy: ProbeObservation(
            status_code=200,
            content_type="application/rss+xml",
            content_bytes=128,
            final_url=source.url,
        ),
    ).run()

    payload = result.to_dict()
    assert payload["checked_count"] == 1
    assert payload["succeeded_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["entries"][0]["health"]["status"] == "healthy"
    assert manager.get("rss-example").last_success_at == datetime(2026, 5, 11, tzinfo=UTC)
    assert [event.event_type for event in result.events] == [
        "source_probe_started",
        "source_probe_succeeded",
        "source_health_updated",
    ]


def test_source_health_checker_records_failure_and_cooldown_event() -> None:
    registry = SourceRegistry([_source()])
    manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=60,
        now=lambda: datetime(2026, 5, 11, tzinfo=UTC),
    )

    def fail(source, policy):
        raise TimeoutError("timed out")

    result = SourceHealthChecker(registry, manager, probe_fetcher=fail).run()

    entry = result.entries[0]
    assert result.failed_count == 1
    assert entry.ok is False
    assert entry.error is not None
    assert entry.error.error_type == "fetch_timeout"
    assert entry.health is not None
    assert entry.health.status == SourceHealthStatus.DOWN
    assert any(event.event_type == "source_cooldown_started" for event in result.events)


def test_source_health_checker_skips_active_cooldown_without_force() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    registry = SourceRegistry([_source()])
    manager = BasicSourceHealthManager(failure_threshold=1, now=lambda: now)
    manager.record_failure(
        "rss-example",
        SourceError(
            source_id="rss-example",
            error_type="fetch_timeout",
            error_message="timed out",
        ),
    )

    result = SourceHealthChecker(
        registry,
        manager,
        probe_fetcher=lambda source, policy: ProbeObservation(200, "text/xml", 1),
    ).run()

    assert result.skipped_count == 1
    assert result.entries[0].skip_reason == "cooldown"
    assert result.entries[0].health is not None
    assert result.entries[0].health.cooldown_until == now + timedelta(seconds=300)


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="rss-example",
        name="Example RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
        reliability="high",
        topics=["AI"],
    )
