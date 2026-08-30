import json
from hashlib import sha256

import pytest

from backend.layers.signal.artifacts import SourceArtifactWriter
from framework.agent.artifacts import ArtifactManager
from backend.foundation.models.source import SourceError, SourceFetchRequest, SourceFetchResult


def test_source_artifact_writer_writes_items_errors_and_redacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)

    index = writer.write_source_artifacts(
        "source-run",
        raw_items=[
            {
                "source_id": "feed/source",
                "source_item_id": "item 1",
                "title": "Real source item",
                "url": "https://example.com/item?token=value&topic=ai",
                "raw_content": "<item>Real source content</item>",
                "metadata": {"api_key": "value"},
            }
        ],
        source_fetch_requests=[
            SourceFetchRequest(
                request_id="fetch 1",
                source_id="feed/source",
                source_type="rss",
                url="https://example.com/feed?token=value",
                limit=1,
                metadata={"headers": {"Authorization": "Bearer hidden-token"}},
            )
        ],
        source_fetch_results=[
            SourceFetchResult(
                request_id="fetch 1",
                source_id="feed/source",
                success=False,
                status_code=200,
                content_type="application/rss+xml",
                error_type="fetch_timeout",
                error_message="timeout",
                metadata={
                    "headers": {"Authorization": "Bearer hidden-token"},
                    "response_headers": {
                        "Content-Type": "application/rss+xml",
                        "Set-Cookie": "session=hidden-cookie",
                    },
                    "response_url": "https://example.com/feed?token=value",
                },
            )
        ],
        source_errors=[
            SourceError(
                source_id="feed/source",
                source_name="Feed Source",
                error_type="fetch_timeout",
                error_message="timeout",
                url="https://example.com/feed?access_token=value&topic=ai",
                retryable=True,
            )
        ],
    )

    assert index is not None
    assert index["item_count"] == 1
    assert index["error_count"] == 1
    assert index["raw_content_count"] == 1
    assert index["fetch_request_count"] == 1
    assert index["fetch_result_count"] == 1
    assert index["parsed_items_count"] == 1
    assert index["response_headers_count"] == 1

    run_dir = tmp_path / "source-run"
    persisted_index = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    assert persisted_index == index

    item_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_item")
    item_payload = json.loads((run_dir / item_entry["path"]).read_text())
    raw_content = "<item>Real source content</item>"
    item_bytes = (run_dir / item_entry["path"]).read_bytes()
    assert item_entry["size_bytes"] == (run_dir / item_entry["path"]).stat().st_size
    assert item_entry["artifact_id"] == "source-item-feed_source-item_1"
    assert item_entry["content_type"] == "application/json"
    assert item_entry["checksum"] == sha256(item_bytes).hexdigest()
    assert item_entry["redacted"] is True
    assert item_entry["artifact_ref"]["artifact_id"] == item_entry["artifact_id"]
    assert item_entry["artifact_ref"]["artifact_type"] == "source_item"
    assert item_entry["artifact_ref"]["path"] == item_entry["path"]
    assert item_entry["artifact_ref"]["checksum"] == item_entry["checksum"]
    assert item_entry["parse_artifact_ref"]["artifact_id"] == item_entry["artifact_id"]
    assert item_entry["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert item_entry["raw_content_bytes"] == len(raw_content.encode("utf-8"))
    assert item_entry["raw_content_sha256"] == sha256(raw_content.encode("utf-8")).hexdigest()
    assert item_payload["item"]["raw_content"] == "<item>Real source content</item>"
    assert item_payload["item"]["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert item_payload["item"]["parse_artifact_ref"]["artifact_type"] == "source_item"
    assert item_payload["item"]["lineage"]["source_id"] == "feed/source"
    assert item_payload["item"]["lineage"]["source_item_id"] == "item 1"
    assert item_payload["item"]["lineage"]["raw_url"] == "https://example.com/item?token=%5BREDACTED%5D&topic=ai"
    assert item_payload["item"]["lineage"]["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert item_payload["item"]["lineage"]["parse_artifact_ref"]["artifact_type"] == "source_item"
    assert item_payload["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert item_payload["parse_artifact_ref"]["artifact_id"] == item_entry["artifact_id"]
    assert item_payload["item"]["metadata"]["api_key"] == "[REDACTED]"

    raw_content_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_raw_content"
    )
    raw_content_path = run_dir / raw_content_entry["path"]
    assert raw_content_path.exists()
    assert raw_content_entry["path"].endswith("/raw_content.bin")
    assert raw_content_path.read_text(encoding="utf-8") == "<item>Real source content</item>"
    assert raw_content_entry["content_type"] == "application/octet-stream"
    assert raw_content_entry["artifact_ref"]["artifact_type"] == "source_raw_content"
    assert raw_content_entry["raw_content_sha256"] == sha256(raw_content.encode("utf-8")).hexdigest()

    parsed_items_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_parsed_items"
    )
    parsed_items_payload = json.loads((run_dir / parsed_items_entry["path"]).read_text())
    assert parsed_items_entry["path"] == "sources/feed_source/parsed_items.json"
    assert parsed_items_entry["artifact_id"] == "source-parsed-items-feed_source-parsed_items"
    assert parsed_items_entry["item_count"] == 1
    assert parsed_items_entry["item_artifact_refs"] == [item_entry["artifact_ref"]]
    assert parsed_items_payload["item_count"] == 1
    assert parsed_items_payload["items"][0]["item"]["title"] == "Real source item"
    assert "raw_content" not in parsed_items_payload["items"][0]["item"]
    assert parsed_items_payload["items"][0]["item"]["metadata"]["api_key"] == "[REDACTED]"
    assert parsed_items_payload["items"][0]["item_artifact_ref"] == item_entry["artifact_ref"]
    assert parsed_items_payload["items"][0]["item"]["lineage"]["parse_artifact_ref"] == item_entry["artifact_ref"]

    fetch_result_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_result"
    )
    fetch_result_payload = json.loads((run_dir / fetch_result_entry["path"]).read_text())
    assert fetch_result_entry["artifact_id"] == "source-fetch-result-feed_source-fetch_1"
    assert fetch_result_payload["fetch_result"]["request_id"] == "fetch 1"
    assert fetch_result_payload["fetch_result"]["metadata"]["headers"]["Authorization"] == "[REDACTED]"
    assert fetch_result_payload["fetch_result"]["response_headers_ref"]["artifact_type"] == (
        "source_response_headers"
    )
    assert "hidden-token" not in json.dumps(fetch_result_payload)

    response_headers_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_response_headers"
    )
    response_headers_payload = json.loads((run_dir / response_headers_entry["path"]).read_text())
    assert response_headers_entry["artifact_id"] == "source-response-headers-feed_source-fetch_1"
    assert response_headers_entry["status_code"] == 200
    assert response_headers_entry["content_type"] == "application/rss+xml"
    assert response_headers_payload["headers"]["Content-Type"] == "application/rss+xml"
    assert response_headers_payload["headers"]["Set-Cookie"] == "[REDACTED]"
    assert response_headers_payload["response_url"] == "https://example.com/feed?token=%5BREDACTED%5D"
    assert fetch_result_payload["response_headers_ref"] == response_headers_entry["artifact_ref"]
    assert fetch_result_payload["fetch_result"]["response_headers_ref"] == response_headers_entry["artifact_ref"]
    assert "hidden-cookie" not in json.dumps(response_headers_payload)

    fetch_request_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_request"
    )
    fetch_request_payload = json.loads((run_dir / fetch_request_entry["path"]).read_text())
    assert fetch_request_entry["artifact_id"] == "source-fetch-request-feed_source-fetch_1"
    assert fetch_request_payload["fetch_request"]["request_id"] == "fetch 1"
    assert fetch_request_payload["fetch_request"]["url"] == "https://example.com/feed?token=%5BREDACTED%5D"
    assert fetch_request_payload["fetch_request"]["metadata"]["headers"]["Authorization"] == "[REDACTED]"

    error_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_error")
    error_payload = json.loads((run_dir / error_entry["path"]).read_text())
    error_bytes = (run_dir / error_entry["path"]).read_bytes()
    assert error_entry["size_bytes"] == (run_dir / error_entry["path"]).stat().st_size
    assert error_entry["artifact_id"].startswith("source-error-feed_source-0001_feed_source_fetch_timeout_")
    assert error_entry["content_type"] == "application/json"
    assert error_entry["checksum"] == sha256(error_bytes).hexdigest()
    assert error_entry["redacted"] is True
    assert error_entry["artifact_ref"]["artifact_id"] == error_entry["artifact_id"]
    assert error_entry["artifact_ref"]["artifact_type"] == "source_error"
    assert error_payload["error"]["error_type"] == "fetch_timeout"
    assert error_payload["error"]["source_name"] == "Feed Source"
    assert error_payload["error"]["retryable"] is True
    assert error_payload["request_ref"] == fetch_request_entry["artifact_ref"]
    assert error_payload["response_ref"] == fetch_result_entry["artifact_ref"]
    assert error_payload["error"]["request_ref"] == fetch_request_entry["artifact_ref"]
    assert error_payload["error"]["response_ref"] == fetch_result_entry["artifact_ref"]
    assert error_entry["request_ref"] == fetch_request_entry["artifact_ref"]
    assert error_entry["response_ref"] == fetch_result_entry["artifact_ref"]
    assert "value" not in json.dumps(error_payload)


def test_source_artifact_writer_redacts_url_userinfo_and_basic_auth(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)

    index = writer.write_source_artifacts(
        "source-run",
        raw_items=[
            {
                "source_id": "feed",
                "source_item_id": "item",
                "title": "Private item",
                "url": "https://reader:password@example.com/item",
                "raw_content": "Authorization: Basic hiddenbasicvalue",
            }
        ],
        source_fetch_requests=[
            SourceFetchRequest(
                request_id="fetch",
                source_id="feed",
                source_type="rss",
                url="https://reader:password@example.com/feed?api_key=value&topic=ai",
            )
        ],
        source_fetch_results=[
            SourceFetchResult(
                request_id="fetch",
                source_id="feed",
                success=True,
                metadata={
                    "response_url": "https://reader:password@example.com/feed?token=value",
                    "response_headers": {"Content-Type": "application/rss+xml"},
                },
            )
        ],
    )

    run_dir = tmp_path / "source-run"
    serialized_index = json.dumps(index)
    assert "reader" not in serialized_index
    assert "password" not in serialized_index
    assert "hiddenbasicvalue" not in serialized_index

    item_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_item")
    item_payload = json.loads((run_dir / item_entry["path"]).read_text())
    assert item_payload["item"]["url"] == "https://[REDACTED]@example.com/item"

    raw_content_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_raw_content"
    )
    raw_content = (run_dir / raw_content_entry["path"]).read_text(encoding="utf-8")
    assert raw_content == "Authorization: Basic [REDACTED]"

    request_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_request"
    )
    request_payload = json.loads((run_dir / request_entry["path"]).read_text())
    assert request_payload["fetch_request"]["url"] == (
        "https://[REDACTED]@example.com/feed?api_key=%5BREDACTED%5D&topic=ai"
    )

    headers_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_response_headers"
    )
    headers_payload = json.loads((run_dir / headers_entry["path"]).read_text())
    assert headers_payload["response_url"] == (
        "https://[REDACTED]@example.com/feed?token=%5BREDACTED%5D"
    )


def test_source_artifact_writer_uses_projected_source_item_id_for_parsed_items(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)

    index = writer.write_source_artifacts(
        "source-run",
        raw_items=[
            {
                "source_id": "feed",
                "title": "Legacy item without id",
                "url": "https://example.com/item",
            }
        ],
    )

    assert index is not None
    run_dir = tmp_path / "source-run"
    item_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_item")
    parsed_items_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_parsed_items"
    )
    parsed_items_payload = json.loads((run_dir / parsed_items_entry["path"]).read_text())

    assert parsed_items_payload["items"][0]["source_item_id"] == item_entry["object_id"]
    assert parsed_items_payload["items"][0]["item_artifact_ref"] == item_entry["artifact_ref"]


def test_source_artifact_writer_normalizes_serialized_error_payloads(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)

    index = writer.write_source_artifacts(
        "source-run",
        source_fetch_requests=[
            SourceFetchRequest(
                request_id="fetch-legacy",
                source_id="feed",
                source_type="rss",
                url="https://example.com/feed",
            )
        ],
        source_fetch_results=[
            SourceFetchResult(
                request_id="fetch-legacy",
                source_id="feed",
                success=False,
                error_type="fetch_timeout",
                error_message="timeout",
            )
        ],
        source_errors=[
            {
                "source_id": "feed",
                "source_name": "Feed",
                "error_type": "fetch_timeout",
                "error_message": "timeout",
                "metadata": {"request_id": "fetch-legacy"},
            }
        ],
    )

    assert index is not None
    run_dir = tmp_path / "source-run"
    error_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_error")
    request_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_request"
    )
    response_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_result"
    )
    error_payload = json.loads((run_dir / error_entry["path"]).read_text())

    assert error_payload["error"]["source_id"] == "feed"
    assert error_payload["error"]["source_name"] == "Feed"
    assert error_payload["error"]["error_type"] == "fetch_timeout"
    assert error_payload["error"]["retryable"] is True
    assert error_entry["request_id"] == "fetch-legacy"
    assert error_entry["request_ref"] == request_entry["artifact_ref"]
    assert error_entry["response_ref"] == response_entry["artifact_ref"]
    assert error_payload["error"]["request_ref"] == request_entry["artifact_ref"]
    assert error_payload["error"]["response_ref"] == response_entry["artifact_ref"]


def test_source_artifact_writer_rejects_unstructured_source_errors_at_input_boundary(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)

    with pytest.raises(TypeError, match="source artifact errors entries must be SourceError"):
        writer.write_source_artifacts("source-run", source_errors=["fetch_timeout"])


def test_source_error_artifact_writer_prefers_explicit_error_refs(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")
    writer = SourceArtifactWriter(manager)
    explicit_request_ref = {"artifact_id": "explicit-request-ref", "artifact_type": "source_fetch_request"}
    explicit_response_ref = {"artifact_id": "explicit-response-ref", "artifact_type": "source_fetch_result"}

    index = writer.write_source_artifacts(
        "source-run",
        source_fetch_requests=[
            SourceFetchRequest(
                request_id="fetch-1",
                source_id="feed",
                source_type="rss",
                url="https://example.com/feed",
            )
        ],
        source_fetch_results=[
            SourceFetchResult(
                request_id="fetch-1",
                source_id="feed",
                success=False,
                error_type="fetch_timeout",
                error_message="timeout",
            )
        ],
        source_errors=[
            SourceError(
                source_id="feed",
                source_name="Feed",
                error_type="fetch_timeout",
                error_message="timeout",
                request_ref=explicit_request_ref,
                response_ref=explicit_response_ref,
                metadata={"request_id": "fetch-1"},
            )
        ],
    )

    assert index is not None
    run_dir = tmp_path / "source-run"
    error_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_error")
    error_payload = json.loads((run_dir / error_entry["path"]).read_text())

    assert error_entry["request_ref"] == explicit_request_ref
    assert error_entry["response_ref"] == explicit_response_ref
    assert error_payload["error"]["request_ref"] == explicit_request_ref
    assert error_payload["error"]["response_ref"] == explicit_response_ref
