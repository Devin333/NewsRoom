from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from business.boards.cross_board.workflows.daily_intelligence.source_connector_adapter import (
    fetch_with_registered_connector,
)
from business.foundation.models.source import (
    SourceDefinition,
    SourceFetchRequest,
    SourceFetchResult,
    SourceType,
)
from business.foundation.registry.source_registry import SourceRegistry


def test_registered_protocol_connector_projects_external_fetch_result() -> None:
    source = SourceDefinition(
        source_id="feed",
        name="Feed",
        source_type=SourceType.RSS,
        url="https://example.com/feed.xml",
    )
    connector = _ExternalFetchResultConnector()
    registry = SourceRegistry([source], connectors={SourceType.RSS: connector})
    fetch_request = SourceFetchRequest(
        request_id="fetch-1",
        source_id=source.source_id,
        source_type=source.source_type,
        url=source.url,
    )

    items, errors, fetch_result = fetch_with_registered_connector(
        registry,
        source,
        request={"topic": "AI policy"},
        fetch_request=fetch_request,
        profile="live",
    )

    assert items == []
    assert errors == []
    assert isinstance(fetch_result, SourceFetchResult)
    assert fetch_result.request_id == "fetch-1"
    assert fetch_result.source_id == "feed"
    assert fetch_result.success is True
    assert fetch_result.status_code == 200
    assert fetch_result.content_type == "application/rss+xml"
    assert fetch_result.content_bytes == 128
    assert fetch_result.latency_ms == 42.5
    assert fetch_result.raw_artifact_ref == {"artifact_id": "raw-ref"}
    assert fetch_result.metadata == {"connector": "external"}
    assert connector.parsed_fetch_result is fetch_result


@dataclass(frozen=True)
class _ExternalFetchResult:
    request_id: str
    source_id: str
    success: bool
    status_code: int | None = None
    content_type: str | None = None
    content_bytes: int | None = None
    latency_ms: float | None = None
    raw_artifact_ref: dict[str, str] | None = None
    fetched_at: datetime | None = None
    metadata: dict[str, object] | None = None


class _ExternalFetchResultConnector:
    def __init__(self) -> None:
        self.parsed_fetch_result = None

    def fetch(self, source, request, context):
        return _ExternalFetchResult(
            request_id=request.request_id,
            source_id=source.source_id,
            success=True,
            status_code=200,
            content_type="application/rss+xml",
            content_bytes=128,
            latency_ms=42.5,
            raw_artifact_ref={"artifact_id": "raw-ref"},
            fetched_at=datetime(2026, 6, 3, tzinfo=UTC),
            metadata={"connector": "external"},
        )

    def parse(self, source, fetch_result, context):
        self.parsed_fetch_result = fetch_result
        return []
