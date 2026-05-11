import json

from core.framework.artifacts import ArtifactManager, SourceArtifactWriter
from domain.sources import SourceError


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
        source_errors=[
            SourceError(
                source_id="feed/source",
                error_type="fetch_timeout",
                error_message="timeout",
                url="https://example.com/feed?access_token=value&topic=ai",
            )
        ],
    )

    assert index is not None
    assert index["item_count"] == 1
    assert index["error_count"] == 1

    run_dir = tmp_path / "source-run"
    persisted_index = json.loads((run_dir / "source_artifacts" / "index.json").read_text())
    assert persisted_index == index

    item_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_item")
    item_payload = json.loads((run_dir / item_entry["path"]).read_text())
    assert item_payload["item"]["raw_content"] == "<item>Real source content</item>"
    assert item_payload["item"]["metadata"]["api_key"] == "[REDACTED]"

    error_entry = next(entry for entry in index["entries"] if entry["artifact_type"] == "source_error")
    error_payload = json.loads((run_dir / error_entry["path"]).read_text())
    assert error_payload["error"]["error_type"] == "fetch_timeout"
    assert "value" not in json.dumps(error_payload)
