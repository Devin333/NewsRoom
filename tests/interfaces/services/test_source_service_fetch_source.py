from datetime import UTC, datetime

from backend.foundation.models.source import SourceDefinition, SourceError
from backend.foundation.registry.source_registry import SourceRegistry
from backend.layers.signal.source_health import BasicSourceHealthManager
from interfaces.services.source_service import SourceApplicationService
from infrastructure.external.sources.models import RawSourceItem, SourceError as InfraSourceError


def test_source_service_fetch_source_uses_router() -> None:
    router = _FakeRouter()
    source = SourceDefinition(
        source_id="arxiv-cs-ai",
        name="arXiv cs.AI",
        source_type="arxiv",
        url="https://export.arxiv.org/api/query",
        topics=["ai"],
        metadata={"query": "cat:cs.AI", "priority": "p0"},
    )
    service = SourceApplicationService(
        source_registry=SourceRegistry([source]),
        source_router=router,
    )

    result = service.fetch_source(source_id="arxiv-cs-ai", limit=2)
    payload = result.to_dict()

    assert router.calls == [("arxiv-cs-ai", 2, None)]
    assert payload["source_id"] == "arxiv-cs-ai"
    assert payload["source_type"] == "arxiv"
    assert payload["query"] == "cat:cs.AI"
    assert payload["item_count"] == 1
    assert payload["items"][0]["lineage"]["source_id"] == "arxiv-cs-ai"


def test_source_service_fetch_source_skips_when_health_blocks() -> None:
    router = _FakeRouter()
    source = SourceDefinition(
        source_id="rss",
        name="RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
        topics=["ai"],
    )
    health_manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=300,
        now=lambda: datetime(2026, 5, 23, tzinfo=UTC),
    )
    health_manager.record_failure(
        "rss",
        SourceError(source_id="rss", error_type="fetch_timeout", error_message="timeout"),
    )
    service = SourceApplicationService(
        source_registry=SourceRegistry([source]),
        source_router=router,
        health_manager=health_manager,
    )

    result = service.fetch_source(source_id="rss", limit=1)
    payload = result.to_dict()

    assert router.calls == []
    assert payload["item_count"] == 0
    assert payload["error_count"] == 1
    assert payload["errors"][0]["error_type"] == "source_fetch_skipped"
    assert payload["errors"][0]["metadata"]["skip_reason"] == "cooldown"


def test_source_service_fetch_source_force_bypasses_health_skip() -> None:
    router = _FakeRouter()
    source = SourceDefinition(
        source_id="rss",
        name="RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
        topics=["ai"],
    )
    health_manager = BasicSourceHealthManager(
        failure_threshold=1,
        cooldown_seconds=300,
        now=lambda: datetime(2026, 5, 23, tzinfo=UTC),
    )
    health_manager.record_failure(
        "rss",
        SourceError(source_id="rss", error_type="fetch_timeout", error_message="timeout"),
    )
    service = SourceApplicationService(
        source_registry=SourceRegistry([source]),
        source_router=router,
        health_manager=health_manager,
    )

    payload = service.fetch_source(source_id="rss", limit=1, force=True).to_dict()

    assert router.calls == [("rss", 1, None)]
    assert payload["item_count"] == 1


def test_source_service_fetch_source_records_failure() -> None:
    router = _FakeRouter(errors=True)
    source = SourceDefinition(
        source_id="rss",
        name="RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
        topics=["ai"],
    )
    health_manager = BasicSourceHealthManager(degraded_threshold=1, failure_threshold=3)
    service = SourceApplicationService(
        source_registry=SourceRegistry([source]),
        source_router=router,
        health_manager=health_manager,
    )

    payload = service.fetch_source(source_id="rss", limit=1).to_dict()

    assert payload["error_count"] == 1
    assert health_manager.get("rss").consecutive_failures == 1


class _FakeRouter:
    def __init__(self, *, errors: bool = False) -> None:
        self.calls = []
        self.errors = errors

    def fetch(self, source, *, limit=None, query=None):
        self.calls.append((source.source_id, limit, query))
        if self.errors:
            return [], [
                InfraSourceError(
                    source_id=source.source_id,
                    source_name=source.name,
                    error_type="fetch_timeout",
                    error_message="timeout",
                    url=source.url,
                    metadata={"source_health_affecting": True},
                )
            ]
        return [
            RawSourceItem(
                source_item_id="raw-service",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Fetched item",
                url="https://example.com/item",
                fetched_at=datetime(2026, 5, 23, tzinfo=UTC),
            )
        ], []
