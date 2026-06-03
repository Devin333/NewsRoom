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
