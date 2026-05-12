from datetime import UTC, datetime

from domain.sources import RawSourceItem, SourceDefinition, SourceError
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


def test_source_service_reports_disabled_sources_as_disabled() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="disabled",
                name="Disabled",
                source_type="rss",
                url="https://example.com/rss",
                enabled=False,
            )
        ]
    )

    result = SourceApplicationService(source_registry=registry).source_health(enabled_only=False)

    health = result.to_dict()["health"][0]
    assert health["source_id"] == "disabled"
    assert health["status"] == "disabled"
    assert health["last_error"]["error_type"] == "source_disabled"


def test_source_service_fetches_arxiv_preview() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry([]),
        arxiv_connector=_FakeArxivConnector(),
    )

    result = service.fetch_arxiv(query="cat:cs.AI", limit=1)
    payload = result.to_dict()

    assert payload["source_type"] == "arxiv"
    assert payload["query"] == "cat:cs.AI"
    assert payload["item_count"] == 1
    assert payload["items"][0]["title"] == "Agent Runtime Evaluation"
    assert payload["items"][0]["metadata"]["arxiv_id"] == "2605.00001v1"


def test_source_service_fetches_github_release_preview() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry([]),
        github_connector=_FakeGithubConnector(),
    )

    result = service.fetch_github_releases(repository="owner/repo", limit=1)
    payload = result.to_dict()

    assert payload["source_type"] == "github"
    assert payload["query"] == "owner/repo"
    assert payload["item_count"] == 1
    assert payload["items"][0]["title"] == "Version 1.0.0"
    assert payload["items"][0]["metadata"]["repository"] == "owner/repo"


class _FakeArxivConnector:
    def fetch(self, source, *, query, limit):
        return [
            RawSourceItem(
                source_item_id="raw-arxiv",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Agent Runtime Evaluation",
                url="https://arxiv.org/abs/2605.00001",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                published_at=datetime(2026, 5, 10, tzinfo=UTC),
                summary="Paper summary",
                authors=["Alice Example"],
                tags=["cs.AI"],
                language="en",
                metadata={"arxiv_id": "2605.00001v1"},
            )
        ], []


class _FakeGithubConnector:
    def fetch_releases(self, source, *, repository, limit):
        return [
            RawSourceItem(
                source_item_id="raw-github",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Version 1.0.0",
                url="https://github.com/owner/repo/releases/tag/v1.0.0",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                published_at=datetime(2026, 5, 10, tzinfo=UTC),
                summary="Release notes",
                authors=["maintainer"],
                tags=["v1.0.0"],
                language="en",
                metadata={"repository": "owner/repo"},
            )
        ], []
