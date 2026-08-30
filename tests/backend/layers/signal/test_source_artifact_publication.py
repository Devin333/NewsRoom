import json

from framework.agent.artifacts import ArtifactManager

from backend.layers.signal.source_artifact_publication import (
    SourceArtifactPublicationService,
    source_artifact_manifest_summary,
)


def test_source_artifact_publication_writes_index_and_manifest_summary(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")

    publication = SourceArtifactPublicationService(manager).publish(
        "source-run",
        raw_items=[
            {
                "source_id": "feed",
                "source_item_id": "item-1",
                "title": "Item",
                "url": "https://example.com/item",
                "raw_content": "raw",
            }
        ],
        source_fetch_requests=[
            {
                "request_id": "request-1",
                "source_id": "feed",
                "url": "https://example.com/feed",
            }
        ],
        source_fetch_results=[
            {
                "request_id": "request-1",
                "source_id": "feed",
                "success": True,
                "metadata": {
                    "source_fetch_result_metadata": {
                        "response_headers": {"Content-Type": "application/rss+xml"},
                    },
                },
            }
        ],
    )

    assert publication is not None
    assert publication.manifest_summary == {
        "item_count": 1,
        "error_count": 0,
        "raw_content_count": 1,
        "fetch_request_count": 1,
        "fetch_result_count": 1,
        "total_count": 6,
        "response_headers_count": 1,
        "parsed_items_count": 1,
    }

    index_path = tmp_path / "source-run" / "source_artifacts" / "index.json"
    persisted_index = json.loads(index_path.read_text(encoding="utf-8"))
    assert persisted_index == publication.index


def test_source_artifact_publication_skips_manifest_summary_without_artifacts(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("source-run")

    publication = SourceArtifactPublicationService(manager).publish("source-run")

    assert publication is None


def test_source_artifact_manifest_summary_ignores_malformed_entries_count() -> None:
    summary = source_artifact_manifest_summary(
        {
            "item_count": "2",
            "error_count": None,
            "raw_content_count": 1,
            "fetch_request_count": 1,
            "fetch_result_count": 1,
            "entries": {"not": "a sequence"},
            "response_headers_count": 0,
            "parsed_items_count": "1",
        }
    )

    assert summary == {
        "item_count": 2,
        "error_count": 0,
        "raw_content_count": 1,
        "fetch_request_count": 1,
        "fetch_result_count": 1,
        "total_count": 0,
        "parsed_items_count": 1,
    }
