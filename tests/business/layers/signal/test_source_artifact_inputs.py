from business.foundation.models.source import SourceFetchResult
from business.layers.signal.source_artifact_inputs import source_fetch_result_artifact_inputs


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
