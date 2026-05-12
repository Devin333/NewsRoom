import asyncio
from datetime import UTC, datetime

from domain.sources import RawSourceItem, SourceDefinition, SourceFetchRequest
from sources.connectors import SourceFetchContext, SyncSourceConnectorAdapter


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
    items = asyncio.run(adapter.parse(source, fetch_result, SourceFetchContext(topic="AI")))

    assert fetch_result.success is True
    assert fetch_result.content_bytes == len("content")
    assert fetch_result.metadata["connector_name"] == "_SyncConnector"
    assert items[0].title == "Protocol item"
