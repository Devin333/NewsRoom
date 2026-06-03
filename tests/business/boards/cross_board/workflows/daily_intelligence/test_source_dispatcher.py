from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from business.foundation.models.source import SourceDefinition, SourceFetchRequest, SourceType
from business.foundation.registry.source_registry import SourceRegistry


def test_source_dispatcher_passes_reddit_runtime_options() -> None:
    source = SourceDefinition(
        source_id="reddit",
        name="Reddit MachineLearning",
        source_type=SourceType.REDDIT,
        url="https://www.reddit.com",
        metadata={"subreddit": "MachineLearning", "listing": "new"},
    )
    connector = _RecordingRedditConnector()

    items, errors, result = _dispatcher(source, reddit_connector=connector).fetch_source(
        source,
        request={"topic": "AI policy"},
        fetch_request=SourceFetchRequest(
            request_id="source-fetch-1",
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        profile="live",
        limit=1,
        connector_options=SourceConnectorRuntimeOptions.from_source(
            source,
            request={"topic": "AI policy"},
        ),
    )

    assert items == []
    assert errors == []
    assert result is None
    assert connector.calls == [
        {
            "source_id": "reddit",
            "subreddit": "MachineLearning",
            "listing": "new",
            "limit": 1,
        }
    ]


def test_source_dispatcher_passes_arxiv_runtime_options() -> None:
    source = SourceDefinition(
        source_id="arxiv",
        name="arXiv",
        source_type=SourceType.ARXIV,
        url="https://export.arxiv.org/api/query",
        metadata={},
    )
    connector = _RecordingArxivConnector()

    items, errors, result = _dispatcher(source, arxiv_connector=connector).fetch_source(
        source,
        request={"topic": "cat:cs.LG"},
        fetch_request=SourceFetchRequest(
            request_id="source-fetch-1",
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        profile="live",
        limit=1,
        connector_options=SourceConnectorRuntimeOptions.from_source(
            source,
            request={"topic": "cat:cs.LG"},
        ),
    )

    assert items == []
    assert errors == []
    assert result is None
    assert connector.calls == [
        {
            "source_id": "arxiv",
            "query": "cat:cs.LG",
            "limit": 1,
        }
    ]


def test_source_dispatcher_passes_hackernews_runtime_options() -> None:
    source = SourceDefinition(
        source_id="hackernews",
        name="Hacker News",
        source_type=SourceType.HACKERNEWS,
        url="https://hacker-news.firebaseio.com/v0",
        metadata={"story_list": "newstories"},
    )
    connector = _RecordingHackerNewsConnector()

    items, errors, result = _dispatcher(source, hackernews_connector=connector).fetch_source(
        source,
        request={"topic": "AI policy"},
        fetch_request=SourceFetchRequest(
            request_id="source-fetch-1",
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        profile="live",
        limit=1,
        connector_options=SourceConnectorRuntimeOptions.from_source(
            source,
            request={"topic": "AI policy"},
        ),
    )

    assert items == []
    assert errors == []
    assert result is None
    assert connector.calls == [
        {
            "source_id": "hackernews",
            "story_list": "newstories",
            "limit": 1,
        }
    ]


def _dispatcher(
    source: SourceDefinition,
    *,
    arxiv_connector=None,
    hackernews_connector=None,
    reddit_connector=None,
) -> SourceDispatcher:
    unused_connector = _UnusedConnector()
    return SourceDispatcher(
        source_registry=SourceRegistry([source]),
        feed_connector=unused_connector,
        html_connector=unused_connector,
        manual_connector=unused_connector,
        arxiv_connector=arxiv_connector or unused_connector,
        github_connector=unused_connector,
        hackernews_connector=hackernews_connector or unused_connector,
        reddit_connector=reddit_connector or unused_connector,
        lobsters_connector=unused_connector,
        stackoverflow_connector=unused_connector,
        devto_connector=unused_connector,
        medium_connector=unused_connector,
    )


class _RecordingRedditConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, subreddit, listing, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "subreddit": subreddit,
                "listing": listing,
                "limit": limit,
            }
        )
        return [], []


class _RecordingArxivConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, query, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "query": query,
                "limit": limit,
            }
        )
        return [], []


class _RecordingHackerNewsConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, story_list, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "story_list": story_list,
                "limit": limit,
            }
        )
        return [], []


class _UnusedConnector:
    def fetch(self, *args, **kwargs):
        raise AssertionError("unexpected connector call")
