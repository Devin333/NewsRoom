from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    source_fetch_request,
)
from business.foundation.models.source import SourceDefinition, SourceType


def test_connector_options_project_arxiv_query_from_metadata_before_request_topic() -> None:
    source = _source(
        source_type=SourceType.ARXIV,
        metadata={"query": "cat:cs.AI"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "fallback topic"},
    )

    assert options.source_type == SourceType.ARXIV
    assert options.query == "cat:cs.AI"


def test_connector_options_project_arxiv_query_from_request_topic() -> None:
    source = _source(
        source_type=SourceType.ARXIV,
        metadata={},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "cat:cs.LG"},
    )

    assert options.query == "cat:cs.LG"


def test_connector_options_project_github_repository_and_topic_query() -> None:
    source = _source(
        source_type=SourceType.GITHUB,
        metadata={"repository": "owner/repo"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "AI policy"},
    )

    assert options.repository == "owner/repo"
    assert options.query == "AI policy"


def test_connector_options_project_github_mode_as_runtime_option() -> None:
    source = _source(
        source_type=SourceType.GITHUB,
        metadata={"repository": "owner/repo", "github_mode": "commits"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "AI policy"},
    )

    assert options.github_mode == "commits"


def test_connector_options_project_legacy_github_mode_key() -> None:
    source = _source(
        source_type=SourceType.GITHUB,
        metadata={"repository": "owner/repo", "mode": "pull_requests"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "AI policy"},
    )

    assert options.github_mode == "pull_requests"


def test_connector_options_project_github_mode_before_legacy_mode() -> None:
    source = _source(
        source_type=SourceType.GITHUB,
        metadata={"repository": "owner/repo", "github_mode": "issues", "mode": "commits"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "AI policy"},
    )

    assert options.github_mode == "issues"


def test_connector_options_project_stackoverflow_tagged_before_tag() -> None:
    source = _source(
        source_type=SourceType.STACKOVERFLOW,
        metadata={"tagged": "python", "tag": "ai", "site": "stackoverflow"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.tag == "python"
    assert options.site == "stackoverflow"


def test_connector_options_project_community_tag() -> None:
    source = _source(
        source_type=SourceType.DEVTO,
        metadata={"tag": "ai"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.tag == "ai"


def test_connector_options_project_reddit_runtime_options() -> None:
    source = _source(
        source_type=SourceType.REDDIT,
        metadata={"subreddit": "MachineLearning", "listing": "top", "time_range": "week"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.subreddit == "MachineLearning"
    assert options.listing == "top"
    assert options.time_range == "week"


def test_connector_options_project_manual_records_as_formal_payload() -> None:
    records = [
        {
            "title": "Manual item",
            "url": "https://example.com/manual",
        }
    ]
    source = _source(
        source_type=SourceType.MANUAL,
        metadata={"records": records},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.manual_records is not None
    assert options.manual_records.records == records


def test_connector_options_ignore_invalid_manual_records_for_connector_legacy_error() -> None:
    source = _source(
        source_type=SourceType.MANUAL,
        metadata={"records": "invalid"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.manual_records is None


def test_connector_options_project_legacy_reddit_time_key() -> None:
    source = _source(
        source_type=SourceType.REDDIT,
        metadata={"subreddit": "MachineLearning", "listing": "top", "time": "month"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.time_range == "month"


def test_connector_options_project_reddit_time_range_before_legacy_time() -> None:
    source = _source(
        source_type=SourceType.REDDIT,
        metadata={
            "subreddit": "MachineLearning",
            "listing": "top",
            "time_range": "week",
            "time": "month",
        },
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.time_range == "week"


def test_connector_options_project_hackernews_story_list() -> None:
    source = _source(
        source_type=SourceType.HACKERNEWS,
        metadata={"story_list": "newstories"},
    )

    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "ignored"},
    )

    assert options.story_list == "newstories"


def test_source_fetch_request_consumes_connector_options_for_arxiv_query() -> None:
    source = _source(
        source_type=SourceType.ARXIV,
        metadata={"query": "cat:cs.AI"},
    )
    options = SourceConnectorRuntimeOptions.from_source(
        source,
        request={"topic": "fallback topic"},
    )

    request = source_fetch_request(
        source,
        request_id="source-fetch-1",
        request={"topic": "fallback topic"},
        limit=3,
        profile="live",
        connector_options=options,
    )

    assert request.query == "cat:cs.AI"
    assert request.connector_name == "ArxivConnector"
    assert request.metadata["connector_name"] == "ArxivConnector"


def _source(
    *,
    source_type: SourceType,
    metadata: dict[str, object],
) -> SourceDefinition:
    return SourceDefinition(
        source_id="source-1",
        name="Source",
        source_type=source_type,
        url="https://example.com/source",
        metadata=metadata,
    )
