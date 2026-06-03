from datetime import UTC, datetime, timedelta

from business.foundation.models.source import SourceDefinition, SourceError, SourceFetchPolicy, SourceHealthStatus
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_processing.error_metadata import SOURCE_ERROR_RUNTIME_METADATA_KEY
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.layers.signal.source_health import BasicSourceHealthManager, ProbeObservation, SourceHealthChecker


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
    assert entry.error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "probe",
        "retryable": True,
        "source_health_affecting": True,
    }
    assert entry.error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": True,
        "workflow_blocking": False,
        "operator_action_required": False,
    }
    assert entry.error.metadata["phase"] == "probe"
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


def test_source_health_checker_rate_limits_same_domain_before_probe() -> None:
    registry = SourceRegistry(
        [
            _source(source_id="first", url="https://example.com/first.xml"),
            _source(source_id="second", url="https://example.com/second.xml"),
        ]
    )
    manager = BasicSourceHealthManager(now=lambda: datetime(2026, 5, 11, tzinfo=UTC))
    probed_urls = []

    def probe(source, policy):
        probed_urls.append(source.url)
        return ProbeObservation(
            status_code=200,
            content_type="application/rss+xml",
            content_bytes=64,
            final_url=source.url,
        )

    result = SourceHealthChecker(
        registry,
        manager,
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
        probe_fetcher=probe,
    ).run()

    assert result.checked_count == 2
    assert result.succeeded_count == 1
    assert result.skipped_count == 1
    assert probed_urls == ["https://example.com/first.xml"]
    skipped = result.entries[1]
    assert skipped.source_id == "second"
    assert skipped.skip_reason == "rate_limited"
    assert skipped.error is not None
    assert skipped.error.error_type == "rate_limited"
    assert skipped.error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "fetch",
        "retryable": True,
        "source_health_affecting": False,
    }
    assert skipped.error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
    }
    assert skipped.error.metadata["source_health_affecting"] is False
    assert manager.get("second").consecutive_failures == 0
    assert any(
        event.event_type == "source_fetch_skipped"
        and event.source_id == "second"
        and event.metadata["reason"] == "rate_limited"
        for event in result.events
    )


def _source(
    *,
    source_id: str = "rss-example",
    url: str = "https://example.com/rss.xml",
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        name="Example RSS",
        source_type="rss",
        url=url,
        reliability="high",
        topics=["AI"],
    )
