import asyncio
from datetime import UTC, datetime

import pytest

from business.foundation.models.source import RawSourceItem, SourceDefinition, SourceFetchRequest
from infrastructure.external.sources import SourceFetchContext, SyncSourceConnectorAdapter


class _SyncConnector:
    def fetch(self, source, *, limit=None):
        return [
            RawSourceItem(
                source_item_id="raw-1",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Protocol item",
                url="https://example.com/item",
                fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
                raw_content="content",
            )
        ], []


def test_sync_source_connector_adapter_exposes_target_protocol_shape() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/feed.xml",
    )
    request = SourceFetchRequest(
        request_id="fetch-1",
        source_id=source.source_id,
        source_type=source.source_type,
        limit=1,
    )
    adapter = SyncSourceConnectorAdapter(_SyncConnector(), source_type="rss")

    fetch_result = asyncio.run(adapter.fetch(source, request, SourceFetchContext(topic="AI")))
    with pytest.raises(ValueError, match="already pending"):
        asyncio.run(adapter.fetch(source, request, SourceFetchContext(topic="AI")))
    items = asyncio.run(adapter.parse(source, fetch_result, SourceFetchContext(topic="AI")))

    assert fetch_result.success is True
    assert fetch_result.content_bytes == len("content")
    assert fetch_result.metadata["connector_name"] == "_SyncConnector"
    assert items[0].title == "Protocol item"
    assert adapter.pending_result_count == 0

    with pytest.raises(ValueError, match="already consumed"):
        asyncio.run(adapter.parse(source, fetch_result, SourceFetchContext(topic="AI")))


def test_sync_source_connector_adapter_rejects_cross_source_result_reuse() -> None:
    source = _source("source-a")
    other = _source("source-b")
    request = _request(source, "fetch-1")
    adapter = SyncSourceConnectorAdapter(_SyncConnector(), source_type="rss")

    fetch_result = asyncio.run(adapter.fetch(source, request, SourceFetchContext()))

    with pytest.raises(ValueError, match="result identity"):
        asyncio.run(adapter.parse(other, fetch_result, SourceFetchContext()))
    assert adapter.pending_result_count == 1
    assert asyncio.run(adapter.parse(source, fetch_result, SourceFetchContext()))


def test_sync_source_connector_adapter_bounds_unconsumed_results() -> None:
    first_source = _source("source-a")
    second_source = _source("source-b")
    adapter = SyncSourceConnectorAdapter(
        _SyncConnector(),
        source_type="rss",
        max_pending_results=1,
    )

    first_result = asyncio.run(
        adapter.fetch(first_source, _request(first_source, "fetch-1"), SourceFetchContext())
    )
    with pytest.raises(RuntimeError, match="capacity"):
        asyncio.run(
            adapter.fetch(
                second_source,
                _request(second_source, "fetch-2"),
                SourceFetchContext(),
            )
        )

    asyncio.run(adapter.parse(first_source, first_result, SourceFetchContext()))
    second_result = asyncio.run(
        adapter.fetch(
            second_source,
            _request(second_source, "fetch-2"),
            SourceFetchContext(),
        )
    )
    assert asyncio.run(adapter.parse(second_source, second_result, SourceFetchContext()))


def _source(source_id: str) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        name=source_id,
        source_type="rss",
        url=f"https://{source_id}.example/feed.xml",
    )


def _request(source: SourceDefinition, request_id: str) -> SourceFetchRequest:
    return SourceFetchRequest(
        request_id=request_id,
        source_id=source.source_id,
        source_type=source.source_type,
        limit=1,
    )
