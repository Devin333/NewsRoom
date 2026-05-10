from datetime import UTC, datetime

from domain.sources import SourceDefinition, SourceError
from interfaces.services.source_service import SourceApplicationService
from sources import SourceRegistry
from sources.health import BasicSourceHealthManager


def test_source_service_lists_enabled_sources() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                SourceDefinition(
                    source_id="enabled",
                    name="Enabled",
                    source_type="rss",
                    url="https://example.com/rss",
                    reliability="high",
                    topics=["AI"],
                ),
                SourceDefinition(
                    source_id="disabled",
                    name="Disabled",
                    source_type="rss",
                    url="https://example.com/disabled",
                    enabled=False,
                ),
            ]
        )
    )

    result = service.list_sources()

    assert result.to_dict()["source_count"] == 1
    assert result.to_dict()["sources"][0]["source_id"] == "enabled"
    assert result.to_dict()["sources"][0]["reliability"] == "high"


def test_source_service_returns_health_views() -> None:
    registry = SourceRegistry(
        [SourceDefinition(source_id="source-1", name="Source", source_type="rss", url="https://example.com/rss")]
    )
    health_manager = BasicSourceHealthManager(now=lambda: datetime(2026, 5, 11, tzinfo=UTC))
    health_manager.record_failure(
        "source-1",
        SourceError(source_id="source-1", error_type="timeout", error_message="timed out"),
    )
    service = SourceApplicationService(source_registry=registry, health_manager=health_manager)

    result = service.source_health()

    assert result.to_dict()["source_count"] == 1
    assert result.to_dict()["health"][0]["source_id"] == "source-1"
    assert result.to_dict()["health"][0]["status"] == "degraded"
