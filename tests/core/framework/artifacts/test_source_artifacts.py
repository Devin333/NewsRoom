import json
from hashlib import sha256

from core.framework.artifacts import ArtifactManager, SourceArtifactWriter
from domain.sources import SourceError, SourceFetchRequest, SourceFetchResult


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
                error_type="fetch_timeout",
                error_message="timeout",
                metadata={"headers": {"Authorization": "Bearer hidden-token"}},
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
    assert item_payload["raw_artifact_ref"]["artifact_type"] == "source_raw_content"
    assert item_payload["parse_artifact_ref"]["artifact_id"] == item_entry["artifact_id"]
    assert item_payload["item"]["metadata"]["api_key"] == "[REDACTED]"

    raw_content_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_raw_content"
    )
    raw_content_path = run_dir / raw_content_entry["path"]
    assert raw_content_path.exists()
    assert raw_content_path.read_text(encoding="utf-8") == "<item>Real source content</item>"
    assert raw_content_entry["content_type"] == "text/plain"
    assert raw_content_entry["artifact_ref"]["artifact_type"] == "source_raw_content"
    assert raw_content_entry["raw_content_sha256"] == sha256(raw_content.encode("utf-8")).hexdigest()

    fetch_result_entry = next(
        entry for entry in index["entries"] if entry["artifact_type"] == "source_fetch_result"
    )
    fetch_result_payload = json.loads((run_dir / fetch_result_entry["path"]).read_text())
    assert fetch_result_entry["artifact_id"] == "source-fetch-result-feed_source-fetch_1"
    assert fetch_result_payload["fetch_result"]["request_id"] == "fetch 1"
    assert fetch_result_payload["fetch_result"]["metadata"]["headers"]["Authorization"] == "[REDACTED]"
    assert "hidden-token" not in json.dumps(fetch_result_payload)

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
    assert "value" not in json.dumps(error_payload)
