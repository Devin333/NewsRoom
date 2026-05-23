from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from business.foundation.registry.source_registry import SourceRegistry
from interfaces.services.source_service import SourceApplicationService
from infrastructure.external.sources.models import RawSourceItem


def test_source_service_fetch_category_filters_priority_language_and_region() -> None:
    sources = [
        _source("research-p0-en", category="research", priority="p0", language="en", region="global"),
        _source("research-p1-zh", category="research", priority="p1", language="zh", region="cn"),
        _source("official-p0-en", category="official_blog", priority="p0", language="en", region="global"),
    ]
    router = _FakeRouter()
    service = SourceApplicationService(
        source_registry=SourceRegistry(sources),
        source_router=router,
    )

    payload = service.fetch_category(
        category="research",
        priority="p1",
        language="zh",
        region="cn",
        limit_per_source=2,
    ).to_dict()

    assert payload["source_count"] == 1
    assert payload["item_count"] == 1
    assert router.calls == [("research-p1-zh", 2)]


def test_source_service_fetch_priority_uses_metadata_priority() -> None:
    router = _FakeRouter()
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                _source("p0-a", category="research", priority="p0"),
                _source("p1-a", category="research", priority="p1"),
                _source("p0-b", category="official_blog", priority="p0"),
            ]
        ),
        source_router=router,
    )

    payload = service.fetch_priority(priority="p0", limit_per_source=1).to_dict()

    assert payload["source_count"] == 2
    assert [call[0] for call in router.calls] == ["p0-a", "p0-b"]


def test_source_service_fetch_topic_sources_includes_selection_report() -> None:
    router = _FakeRouter()
    service = SourceApplicationService(
        source_registry=SourceRegistry(
            [
                _source("agent-framework", category="agent_framework", priority="p0", topics=["agent", "framework"]),
                _source("research", category="research", priority="p1", topics=["paper"]),
            ]
        ),
        source_router=router,
    )

    payload = service.fetch_topic_sources(topic="AI agent frameworks", limit_per_source=1).to_dict()

    assert payload["source_count"] == 1
    assert payload["selection_report"]["topic"] == "AI agent frameworks"
    assert payload["selection_report"]["selected_source_ids"] == ["agent-framework"]
    assert payload["selection_report"]["fallback_used"] is False


def test_source_service_fetch_batch_reports_skipped_sources() -> None:
    disabled = _source("disabled", category="research", priority="p0")
    disabled = SourceDefinition(
        source_id=disabled.source_id,
        name=disabled.name,
        source_type=disabled.source_type,
        url=disabled.url,
        enabled=False,
        topics=list(disabled.topics),
        category=disabled.category,
        metadata=dict(disabled.metadata),
    )
    service = SourceApplicationService(
        source_registry=SourceRegistry([disabled]),
        source_router=_FakeRouter(),
    )

    payload = service.fetch_category(
        category="research",
        enabled_only=False,
        limit_per_source=1,
    ).to_dict()

    assert payload["source_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["results"][0]["errors"][0]["metadata"]["skip_reason"] == "disabled"


def _source(
    source_id: str,
    *,
    category: str,
    priority: str,
    language: str = "en",
    region: str = "global",
    topics: list[str] | None = None,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        name=source_id,
        source_type="rss",
        url=f"https://example.com/{source_id}.xml",
        topics=topics or ["ai"],
        category=category,
        language=language,
        region=region,
        metadata={"group": category, "priority": priority, "signal_kind": "community_trend"},
    )


class _FakeRouter:
    def __init__(self) -> None:
        self.calls = []

    def fetch(self, source, *, limit=None, query=None):
        self.calls.append((source.source_id, limit))
        return [
            RawSourceItem(
                source_item_id=f"raw-{source.source_id}",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title=f"Fetched {source.source_id}",
                url=f"https://example.com/{source.source_id}/item",
                fetched_at=datetime(2026, 5, 23, tzinfo=UTC),
            )
        ], []
