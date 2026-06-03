from datetime import datetime, timezone

from business.foundation.models.source import RawSourceItem, SourceFetchResult
from business.layers.signal.source_artifact_inputs import (
    source_fetch_result_artifact_inputs,
    source_item_artifact_inputs,
)


def test_source_item_artifact_input_projects_formal_raw_source_item() -> None:
    [artifact_input] = source_item_artifact_inputs(
        [
            RawSourceItem(
                source_item_id="raw-1",
                source_id="feed",
                source_name="Feed",
                source_type="rss",
                title="Item",
                url="https://example.com/item",
                fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                raw_content="raw body",
                raw_artifact_ref={"artifact_id": "raw-ref"},
                parse_artifact_ref={"artifact_id": "parse-ref"},
            )
        ]
    )

    assert artifact_input.source_item_id == "raw-1"
    assert artifact_input.source_id == "feed"
    assert artifact_input.raw_content == "raw body"
    assert artifact_input.raw_artifact_ref == {"artifact_id": "raw-ref"}
    assert artifact_input.parse_artifact_ref == {"artifact_id": "parse-ref"}


def test_source_item_artifact_input_accepts_legacy_mapping_payload() -> None:
    [artifact_input] = source_item_artifact_inputs(
        [
            {
                "title": "Legacy item",
                "raw_content": "legacy raw body",
                "raw_artifact_ref": {"artifact_id": "raw-ref"},
            }
        ]
    )

    assert artifact_input.source_item_id
    assert artifact_input.source_id == "unknown-source"
    assert artifact_input.raw_content == "legacy raw body"
    assert artifact_input.raw_artifact_ref == {"artifact_id": "raw-ref"}
    assert artifact_input.parse_artifact_ref is None


def test_source_fetch_result_artifact_input_projects_formal_result_metadata() -> None:
    [artifact_input] = source_fetch_result_artifact_inputs(
        [
            SourceFetchResult(
                request_id="fetch-1",
                source_id="feed",
                success=True,
                status_code=200,
                content_type="application/rss+xml",
                metadata={
                    "response_url": "https://example.com/feed",
                    "response_headers": {"Content-Type": "application/rss+xml"},
                },
            )
        ]
    )

    assert artifact_input.request_id == "fetch-1"
    assert artifact_input.source_id == "feed"
    assert artifact_input.status_code == 200
    assert artifact_input.content_type == "application/rss+xml"
    assert artifact_input.response_url == "https://example.com/feed"
    assert artifact_input.response_headers == {"Content-Type": "application/rss+xml"}


def test_source_fetch_result_artifact_input_accepts_legacy_mapping_payload() -> None:
    [artifact_input] = source_fetch_result_artifact_inputs(
        [
            {
                "request_id": "fetch-legacy",
                "source_id": "feed",
                "success": True,
                "status_code": "200",
                "content_type": "application/rss+xml",
                "metadata": {
                    "fetch_response": {
                        "url": "https://example.com/feed",
                        "headers": {"Content-Type": "application/rss+xml"},
                    }
                },
            }
        ]
    )

    assert artifact_input.request_id == "fetch-legacy"
    assert artifact_input.source_id == "feed"
    assert artifact_input.status_code == 200
    assert artifact_input.content_type == "application/rss+xml"
    assert artifact_input.response_url is None
    assert artifact_input.response_headers == {"Content-Type": "application/rss+xml"}
