from datetime import UTC, datetime

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from interfaces.services.source_service import SourceApplicationService
from sources import SourceRegistry
from sources.health import BasicSourceHealthManager, ProbeObservation


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
                    fetch_interval_seconds=1800,
                    user_agent="NewsRoomSummary/1.0",
                    topics=["AI"],
                    category="official",
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
    assert result.to_dict()["sources"][0]["category"] == "official"
    assert result.to_dict()["sources"][0]["fetch_interval_seconds"] == 1800
    assert result.to_dict()["sources"][0]["user_agent"] == "NewsRoomSummary/1.0"


def test_source_service_get_source_returns_target_summary_fields() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                SourceDefinition(
                    source_id="source-1",
                    name="Source",
                    source_type="rss",
                    url="https://example.com/rss",
                    reliability="high",
                    fetch_interval_seconds=900,
                    user_agent="NewsRoomDetail/1.0",
                    topics=["AI"],
                    category="research",
                    language="en",
                    region="global",
                )
            ]
        )
    )

    payload = service.get_source("source-1").to_dict()

    assert payload["source_id"] == "source-1"
    assert payload["category"] == "research"
    assert payload["fetch_interval_seconds"] == 900
    assert payload["user_agent"] == "NewsRoomDetail/1.0"
    assert payload["language"] == "en"
    assert payload["region"] == "global"


def test_source_service_filters_sources_by_reliability() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                SourceDefinition(
                    source_id="high",
                    name="High",
                    source_type="rss",
                    url="https://example.com/high",
                    reliability="high",
                ),
                SourceDefinition(
                    source_id="low",
                    name="Low",
                    source_type="rss",
                    url="https://example.com/low",
                    reliability="low",
                ),
            ]
        )
    )

    result = service.list_sources(reliability="high")

    assert result.to_dict()["source_count"] == 1
    assert result.to_dict()["sources"][0]["source_id"] == "high"


def test_source_service_validates_registry() -> None:
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                SourceDefinition(
                    source_id="bad/source",
                    name="Bad",
                    source_type="rss",
                    url="fixture://bad",
                    topics=["ai"],
                )
            ]
        )
    )

    result = service.validate_sources()
    payload = result.to_dict()

    assert payload["is_valid"] is False
    assert payload["error_count"] >= 2


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
    assert result.to_dict()["health"][0]["source_name"] == "Source"
    assert result.to_dict()["health"][0]["url"] == "https://example.com/rss"
    assert result.to_dict()["health"][0]["status"] == "healthy"


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
    assert health["source_name"] == "Disabled"
    assert health["url"] == "https://example.com/rss"
    assert health["status"] == "disabled"
    assert health["last_error"]["error_type"] == "source_disabled"


def test_source_service_checks_source_health_with_real_checker_path() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="source-1",
                name="Source",
                source_type="rss",
                url="https://example.com/rss",
                topics=["AI"],
            )
        ]
    )
    service = SourceApplicationService(
        source_registry=registry,
        health_probe_fetcher=lambda source, policy: ProbeObservation(
            status_code=200,
            content_type="application/rss+xml",
            content_bytes=42,
            final_url=source.url,
        ),
    )

    payload = service.check_source_health(source_id="source-1").to_dict()

    assert payload["checked_count"] == 1
    assert payload["succeeded_count"] == 1
    assert payload["entries"][0]["source_id"] == "source-1"
    assert payload["entries"][0]["health"]["status"] == "healthy"


def test_source_service_health_check_uses_configured_fetch_policy(tmp_path) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
fetch:
  timeout_seconds: 6
  max_bytes: 4096
  max_redirects: 4
  user_agent: NewsRoomSourceService/1.0
  respect_robots: false
rss_feeds:
  - source_id: source-1
    name: Source
    url: https://example.com/rss
    topics: [ai]
""".strip(),
        encoding="utf-8",
    )
    captured = {}

    def probe(source, policy):
        captured["source_id"] = source.source_id
        captured["timeout_seconds"] = policy.timeout_seconds
        captured["max_bytes"] = policy.max_bytes
        captured["max_redirects"] = policy.max_redirects
        captured["user_agent"] = policy.user_agent
        captured["respect_robots"] = policy.respect_robots
        return ProbeObservation(status_code=200, content_type="application/rss+xml", content_bytes=10)

    service = SourceApplicationService(
        source_config_path=config_path,
        health_probe_fetcher=probe,
    )

    result = service.check_source_health(source_id="source-1")

    assert result.succeeded_count == 1
    assert captured == {
        "source_id": "source-1",
        "timeout_seconds": 6.0,
        "max_bytes": 4096,
        "max_redirects": 4,
        "user_agent": "NewsRoomSourceService/1.0",
        "respect_robots": False,
    }


def test_source_service_default_preview_connectors_use_configured_fetch_policy(tmp_path) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
fetch:
  timeout_seconds: 8
  max_bytes: 8192
  user_agent: NewsRoomPreview/1.0
  respect_robots: false
rss_feeds:
  - source_id: source-1
    name: Source
    url: https://example.com/rss
    topics: [ai]
""".strip(),
        encoding="utf-8",
    )

    service = SourceApplicationService(source_config_path=config_path)

    assert service.arxiv_connector.fetch_policy.timeout_seconds == 8.0
    assert service.arxiv_connector.fetch_policy.max_bytes == 8192
    assert service.arxiv_connector.fetch_policy.user_agent == "NewsRoomPreview/1.0"
    assert service.github_connector.fetch_policy.timeout_seconds == 8.0
    assert service.github_connector.fetch_policy.max_bytes == 8192
    assert service.github_connector.fetch_policy.user_agent == "NewsRoomPreview/1.0"


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
