from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_connector_options import (
    SourceConnectorRuntimeOptions,
)
from business.boards.cross_board.workflows.daily_intelligence.source_dispatcher import SourceDispatcher
from business.layers.signal.source_processing.error_metadata import SOURCE_ERROR_RUNTIME_METADATA_KEY
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.foundation.models.source import SourceDefinition, SourceFetchRequest, SourceType
from business.foundation.registry.source_registry import SourceRegistry


def test_source_dispatcher_passes_reddit_runtime_options() -> None:
    source = SourceDefinition(
        source_id="reddit",
        name="Reddit MachineLearning",
        source_type=SourceType.REDDIT,
        url="https://www.reddit.com",
        metadata={"subreddit": "MachineLearning", "listing": "top", "time_range": "week"},
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
            "listing": "top",
            "time_range": "week",
            "limit": 1,
        }
    ]


def test_source_dispatcher_passes_manual_records_runtime_options() -> None:
    records = [
        {
            "title": "Manual item",
            "url": "https://example.com/manual",
        }
    ]
    source = SourceDefinition(
        source_id="manual",
        name="Manual",
        source_type=SourceType.MANUAL,
        url="manual://operator",
        metadata={"records": records},
    )
    connector = _RecordingManualConnector()

    items, errors, result = _dispatcher(source, manual_connector=connector).fetch_source(
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
            "source_id": "manual",
            "records": records,
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


def test_source_dispatcher_passes_github_runtime_options() -> None:
    source = SourceDefinition(
        source_id="github",
        name="GitHub",
        source_type=SourceType.GITHUB,
        url="https://api.github.com",
        metadata={"repository": "owner/repo", "mode": "commits", "discussion_category": "Ideas"},
    )
    connector = _RecordingGithubConnector()

    items, errors, result = _dispatcher(source, github_connector=connector).fetch_source(
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
            "source_id": "github",
            "repository": "owner/repo",
            "query": "AI policy",
            "mode": "commits",
            "discussion_category": "Ideas",
            "limit": 1,
        }
    ]


def test_source_dispatcher_passes_devto_runtime_options() -> None:
    source = SourceDefinition(
        source_id="devto",
        name="dev.to",
        source_type=SourceType.DEVTO,
        url="https://dev.to/api",
        metadata={"tag": "ai"},
    )
    connector = _RecordingTagConnector()

    items, errors, result = _dispatcher(source, devto_connector=connector).fetch_source(
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
            "source_id": "devto",
            "tag": "ai",
            "limit": 1,
        }
    ]


def test_source_dispatcher_passes_stackoverflow_runtime_options() -> None:
    source = SourceDefinition(
        source_id="stackoverflow",
        name="Stack Overflow",
        source_type=SourceType.STACKOVERFLOW,
        url="https://api.stackexchange.com/2.3",
        metadata={"tagged": "python", "site": "stackoverflow"},
    )
    connector = _RecordingStackOverflowConnector()

    items, errors, result = _dispatcher(source, stackoverflow_connector=connector).fetch_source(
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
            "source_id": "stackoverflow",
            "tag": "python",
            "site": "stackoverflow",
            "limit": 1,
        }
    ]


def test_source_dispatcher_returns_formal_metadata_for_domain_allowlist_error() -> None:
    source = SourceDefinition(
        source_id="blocked-feed",
        name="Blocked Feed",
        source_type=SourceType.RSS,
        url="https://blocked.example/feed.xml",
    )

    items, errors, result = _dispatcher(
        source,
        feed_connector=_PolicyConnector(allowed_domains=("trusted.example",)),
    ).fetch_source(
        source,
        request={"topic": "AI policy"},
        fetch_request=SourceFetchRequest(
            request_id="source-fetch-1",
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        profile="live",
        limit=1,
    )

    assert items == []
    assert result is None
    assert len(errors) == 1
    error = errors[0]
    assert error.error_type == "source_domain_not_allowed"
    assert error.metadata["phase"] == "fetch"
    assert error.metadata["retryable"] is False
    assert error.metadata["source_health_affecting"] is False
    assert error.metadata["workflow_blocking"] is False
    assert error.metadata["domain"] == "blocked.example"
    assert error.metadata["allowed_domains"] == ["trusted.example"]
    assert error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "fetch",
        "retryable": False,
        "source_health_affecting": False,
    }
    assert error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
    }


def test_source_dispatcher_returns_formal_metadata_for_unsupported_source_type() -> None:
    source = SourceDefinition(
        source_id="paper-index",
        name="Paper Index",
        source_type=SourceType.PAPER_INDEX,
        url="https://papers.example/index",
    )

    items, errors, result = _dispatcher(source).fetch_source(
        source,
        request={"topic": "AI policy"},
        fetch_request=SourceFetchRequest(
            request_id="source-fetch-1",
            source_id=source.source_id,
            source_type=source.source_type,
        ),
        profile="live",
        limit=1,
    )

    assert items == []
    assert result is None
    assert len(errors) == 1
    error = errors[0]
    assert error.error_type == "unsupported_source_type"
    assert error.metadata["phase"] == "fetch"
    assert error.metadata["retryable"] is False
    assert error.metadata["source_health_affecting"] is False
    assert error.metadata["workflow_blocking"] is False
    assert error.metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "fetch",
        "retryable": False,
        "source_health_affecting": False,
    }
    assert error.metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": False,
        "operator_action_required": False,
    }


def _dispatcher(
    source: SourceDefinition,
    *,
    arxiv_connector=None,
    devto_connector=None,
    feed_connector=None,
    github_connector=None,
    hackernews_connector=None,
    manual_connector=None,
    reddit_connector=None,
    stackoverflow_connector=None,
) -> SourceDispatcher:
    unused_connector = _UnusedConnector()
    return SourceDispatcher(
        source_registry=SourceRegistry([source]),
        feed_connector=feed_connector or unused_connector,
        html_connector=unused_connector,
        manual_connector=manual_connector or unused_connector,
        arxiv_connector=arxiv_connector or unused_connector,
        github_connector=github_connector or unused_connector,
        hackernews_connector=hackernews_connector or unused_connector,
        reddit_connector=reddit_connector or unused_connector,
        lobsters_connector=unused_connector,
        stackoverflow_connector=stackoverflow_connector or unused_connector,
        devto_connector=devto_connector or unused_connector,
        medium_connector=unused_connector,
    )


class _RecordingRedditConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, subreddit, listing, time_range, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "subreddit": subreddit,
                "listing": listing,
                "time_range": time_range,
                "limit": limit,
            }
        )
        return [], []


class _RecordingManualConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, records, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "records": records,
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


class _RecordingGithubConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, repository, query, mode, discussion_category, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "repository": repository,
                "query": query,
                "mode": mode,
                "discussion_category": discussion_category,
                "limit": limit,
            }
        )
        return [], []


class _RecordingTagConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, tag, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "tag": tag,
                "limit": limit,
            }
        )
        return [], []


class _RecordingStackOverflowConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch(self, source, *, tag, site, limit):
        self.calls.append(
            {
                "source_id": source.source_id,
                "tag": tag,
                "site": site,
                "limit": limit,
            }
        )
        return [], []


class _PolicyConnector:
    def __init__(self, *, allowed_domains) -> None:
        self.fetch_policy = _FetchPolicy(allowed_domains=allowed_domains)

    def fetch(self, *args, **kwargs):
        raise AssertionError("disallowed source should be rejected before connector fetch")


class _FetchPolicy:
    def __init__(self, *, allowed_domains) -> None:
        self.timeout_seconds = 15.0
        self.max_bytes = 1_000_000
        self.max_redirects = 3
        self.user_agent = "news-intelligence-system"
        self.respect_robots = True
        self.rate_limit_per_domain_per_minute = None
        self.allowed_domains = allowed_domains
        self.retry_times = 2
        self.retry_on_status_codes = (429, 500, 502, 503, 504)


class _UnusedConnector:
    def fetch(self, *args, **kwargs):
        raise AssertionError("unexpected connector call")
