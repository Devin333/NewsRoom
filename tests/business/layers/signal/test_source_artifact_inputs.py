from datetime import datetime, timezone

import pytest

from business.foundation.models.source import RawSourceItem, SourceError, SourceFetchRequest, SourceFetchResult
from business.layers.signal.source_artifact_inputs import (
    source_error_artifact_inputs,
    source_fetch_request_artifact_inputs,
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


def test_source_item_artifact_input_accepts_serialized_item_payload() -> None:
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


def test_source_item_artifact_inputs_reject_single_mapping_payload() -> None:
    with pytest.raises(TypeError, match="source item artifacts must be a sequence"):
        source_item_artifact_inputs({"source_id": "feed", "source_item_id": "item-1"})


def test_source_fetch_request_artifact_input_projects_formal_request() -> None:
    [artifact_input] = source_fetch_request_artifact_inputs(
        [
            SourceFetchRequest(
                request_id="fetch-1",
                source_id="feed",
                source_type="rss",
                url="https://example.com/feed",
            )
        ]
    )

    assert artifact_input.request_id == "fetch-1"
    assert artifact_input.source_id == "feed"


def test_source_fetch_request_artifact_input_accepts_serialized_request_payload() -> None:
    [artifact_input] = source_fetch_request_artifact_inputs(
        [
            {
                "source_type": "rss",
                "url": "https://example.com/feed",
            }
        ]
    )

    assert artifact_input.request_id
    assert artifact_input.source_id == "unknown-source"


def test_source_fetch_request_artifact_inputs_reject_single_mapping_payload() -> None:
    with pytest.raises(TypeError, match="source fetch request artifacts must be a sequence"):
        source_fetch_request_artifact_inputs({"request_id": "fetch-1", "source_id": "feed"})


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


def test_source_fetch_result_artifact_input_projects_formal_nested_metadata() -> None:
    [artifact_input] = source_fetch_result_artifact_inputs(
        [
            SourceFetchResult(
                request_id="fetch-1",
                source_id="feed",
                success=True,
                status_code=200,
                content_type="application/rss+xml",
                metadata={
                    "response_url": "https://legacy.example.com/feed",
                    "response_headers": {"Content-Type": "text/plain"},
                    "source_fetch_result_metadata": {
                        "response_url": "https://formal.example.com/feed",
                        "response_headers": {"Content-Type": "application/rss+xml"},
                    },
                },
            )
        ]
    )

    assert artifact_input.response_url == "https://formal.example.com/feed"
    assert artifact_input.response_headers == {"Content-Type": "application/rss+xml"}


def test_source_fetch_result_artifact_input_accepts_serialized_result_payload() -> None:
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


def test_source_fetch_result_artifact_input_accepts_formal_nested_mapping_payload() -> None:
    [artifact_input] = source_fetch_result_artifact_inputs(
        [
            {
                "request_id": "fetch-formal",
                "source_id": "feed",
                "success": True,
                "status_code": "200",
                "content_type": "application/rss+xml",
                "metadata": {
                    "fetch_response": {
                        "headers": {"Content-Type": "text/plain"},
                    },
                    "source_fetch_result_metadata": {
                        "response_url": "https://formal.example.com/feed",
                        "fetch_response": {
                            "headers": {"Content-Type": "application/rss+xml"},
                        },
                    },
                },
            }
        ]
    )

    assert artifact_input.request_id == "fetch-formal"
    assert artifact_input.response_url == "https://formal.example.com/feed"
    assert artifact_input.response_headers == {"Content-Type": "application/rss+xml"}


def test_source_fetch_result_artifact_inputs_reject_single_mapping_payload() -> None:
    with pytest.raises(TypeError, match="source fetch result artifacts must be a sequence"):
        source_fetch_result_artifact_inputs({"request_id": "fetch-1", "source_id": "feed"})


def test_source_error_artifact_input_projects_formal_error_metadata() -> None:
    [artifact_input] = source_error_artifact_inputs(
        [
            SourceError(
                source_id="feed",
                source_name="Feed",
                error_type="fetch_timeout",
                error_message="timeout",
                request_ref={"artifact_id": "request-ref"},
                response_ref={"artifact_id": "response-ref"},
                metadata={"request_id": "fetch-1"},
            )
        ]
    )

    assert artifact_input.source_id == "feed"
    assert artifact_input.error_id.startswith("0001_feed_fetch_timeout_")
    assert artifact_input.payload.error_type == "fetch_timeout"
    assert artifact_input.request_id == "fetch-1"
    assert artifact_input.request_ref == {"artifact_id": "request-ref"}
    assert artifact_input.response_ref == {"artifact_id": "response-ref"}


def test_source_error_artifact_input_projects_formal_runtime_metadata() -> None:
    [artifact_input] = source_error_artifact_inputs(
        [
            SourceError(
                source_id="feed",
                source_name="Feed",
                error_type="fetch_timeout",
                error_message="timeout",
                request_ref={"artifact_id": "request-ref"},
                metadata={
                    "request_id": "legacy-fetch",
                    "source_error_runtime_metadata": {"request_id": "formal-fetch"},
                },
            )
        ]
    )

    assert artifact_input.request_id == "formal-fetch"
    assert artifact_input.request_ref == {"artifact_id": "request-ref"}


def test_source_error_artifact_input_accepts_serialized_source_error_payload() -> None:
    [artifact_input] = source_error_artifact_inputs(
        [
            {
                "source_id": "feed",
                "source_name": "Feed",
                "error_type": "fetch_timeout",
                "error_message": "timeout",
                "request_ref": {"artifact_id": "request-ref"},
                "metadata": {"request_id": "fetch-legacy"},
            }
        ]
    )

    assert artifact_input.source_id == "feed"
    assert artifact_input.error_id.startswith("0001_feed_fetch_timeout_")
    assert artifact_input.payload.source_name == "Feed"
    assert artifact_input.payload.retryable is True
    assert artifact_input.request_id == "fetch-legacy"
    assert artifact_input.request_ref == {"artifact_id": "request-ref"}
    assert artifact_input.response_ref is None


def test_source_error_artifact_inputs_reject_single_mapping_payload() -> None:
    with pytest.raises(TypeError, match="source artifact errors must be a sequence"):
        source_error_artifact_inputs(
            {
                "source_id": "feed",
                "error_type": "fetch_timeout",
                "error_message": "timeout",
            }
        )


def test_source_error_artifact_inputs_reject_unstructured_source_errors() -> None:
    with pytest.raises(TypeError, match="source artifact errors entries must be SourceError"):
        source_error_artifact_inputs(["fetch_timeout"])
