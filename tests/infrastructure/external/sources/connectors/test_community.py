import json
from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources import (
    DEVTO_API_URL,
    LOBSTERS_BASE_URL,
    MEDIUM_BASE_URL,
    STACKOVERFLOW_API_URL,
    DevToConnector,
    FeedConnector,
    LobstersConnector,
    MediumConnector,
    StackOverflowConnector,
    build_devto_articles_url,
    build_lobsters_url,
    build_medium_feed_url,
    build_stackoverflow_questions_url,
)


LOBSTERS_ITEMS = json.dumps(
    [
        {
            "short_id": "abc",
            "short_id_url": "https://lobste.rs/s/abc",
            "comments_url": "https://lobste.rs/s/abc/comments",
            "title": "Runtime discussion",
            "url": "https://example.com/runtime",
            "description": "Discussion summary",
            "created_at": "2026-05-11T10:00:00Z",
            "submitter_user": "alice",
            "tags": ["ai", "python"],
            "score": 10,
            "comment_count": 3,
        }
    ]
)

STACKOVERFLOW_ITEMS = json.dumps(
    {
        "items": [
            {
                "question_id": 123,
                "title": "How to run a source pipeline?",
                "link": "https://stackoverflow.com/q/123",
                "creation_date": 1778493600,
                "owner": {"display_name": "Bob"},
                "tags": ["python", "workflow"],
                "score": 5,
                "answer_count": 2,
                "is_answered": True,
            }
        ]
    }
)

DEVTO_ITEMS = json.dumps(
    [
        {
            "id": 55,
            "title": "Building source pipelines",
            "url": "https://dev.to/example/source-pipelines",
            "description": "Article summary",
            "published_at": "2026-05-11T10:00:00Z",
            "user": {"username": "devalice"},
            "tag_list": ["ai", "python"],
            "positive_reactions_count": 12,
            "comments_count": 4,
        }
    ]
)

MEDIUM_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Medium Tag</title>
    <item>
      <title>Engineering Post</title>
      <link>https://medium.com/example/engineering-post</link>
      <description>Post summary.</description>
      <pubDate>Mon, 11 May 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_lobsters_connector_fetches_tagged_stories() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return LOBSTERS_ITEMS

    items, errors = LobstersConnector(fetch_text=fetch_text).fetch(
        _source("lobsters", LOBSTERS_BASE_URL, metadata={"tag": "ai"}),
        limit=1,
    )

    assert errors == []
    assert captured["url"] == "https://lobste.rs/t/ai.json"
    assert items[0].title == "Runtime discussion"
    assert items[0].published_at == datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
    assert items[0].authors == ["alice"]
    assert items[0].tags == ["lobsters", "ai", "python"]
    assert items[0].metadata["community_surface"] == "lobsters"


def test_lobsters_connector_fetch_accepts_explicit_runtime_tag() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return LOBSTERS_ITEMS

    items, errors = LobstersConnector(fetch_text=fetch_text).fetch(
        _source("lobsters", LOBSTERS_BASE_URL),
        tag="ai",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == "https://lobste.rs/t/ai.json"
    assert items[0].title == "Runtime discussion"


def test_stackoverflow_connector_fetches_tag_questions() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return STACKOVERFLOW_ITEMS

    items, errors = StackOverflowConnector(fetch_text=fetch_text).fetch(
        _source(
            "stackoverflow",
            STACKOVERFLOW_API_URL,
            metadata={"tagged": "python", "site": "stackoverflow"},
        ),
        limit=1,
    )

    assert errors == []
    assert captured["url"] == (
        "https://api.stackexchange.com/2.3/questions?"
        "order=desc&sort=activity&tagged=python&site=stackoverflow&pagesize=1"
    )
    assert items[0].title == "How to run a source pipeline?"
    assert items[0].authors == ["Bob"]
    assert items[0].metadata["community_surface"] == "stackoverflow"
    assert items[0].metadata["question_id"] == 123


def test_stackoverflow_connector_fetch_accepts_explicit_runtime_options() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return STACKOVERFLOW_ITEMS

    items, errors = StackOverflowConnector(fetch_text=fetch_text).fetch(
        _source("stackoverflow", STACKOVERFLOW_API_URL),
        tag="python",
        site="stackoverflow",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == (
        "https://api.stackexchange.com/2.3/questions?"
        "order=desc&sort=activity&tagged=python&site=stackoverflow&pagesize=1"
    )
    assert items[0].title == "How to run a source pipeline?"


def test_stackoverflow_connector_requires_tag() -> None:
    items, errors = StackOverflowConnector(fetch_text=lambda url: STACKOVERFLOW_ITEMS).fetch(
        _source("stackoverflow", STACKOVERFLOW_API_URL),
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["operator_action_required"] is True


def test_devto_connector_fetches_articles() -> None:
    items, errors = DevToConnector(fetch_text=lambda url: DEVTO_ITEMS).fetch(
        _source("devto", DEVTO_API_URL, metadata={"tag": "ai"}),
        limit=1,
    )

    assert errors == []
    assert items[0].title == "Building source pipelines"
    assert items[0].authors == ["devalice"]
    assert items[0].tags == ["devto", "ai", "python"]
    assert items[0].metadata["community_surface"] == "devto"


def test_devto_connector_fetch_accepts_explicit_runtime_tag() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return DEVTO_ITEMS

    items, errors = DevToConnector(fetch_text=fetch_text).fetch(
        _source("devto", DEVTO_API_URL),
        tag="ai",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == "https://dev.to/api/articles?per_page=1&tag=ai"
    assert items[0].title == "Building source pipelines"


def test_medium_connector_uses_feed_connector_for_tag_feed() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return MEDIUM_FEED

    items, errors = MediumConnector(feed_connector=FeedConnector(fetch_text=fetch_text)).fetch(
        _source("medium", MEDIUM_BASE_URL, metadata={"tag": "engineering"}),
        limit=1,
    )

    assert errors == []
    assert captured["url"] == "https://medium.com/feed/tag/engineering"
    assert items[0].title == "Engineering Post"


def test_medium_connector_fetch_accepts_explicit_runtime_tag() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return MEDIUM_FEED

    items, errors = MediumConnector(feed_connector=FeedConnector(fetch_text=fetch_text)).fetch(
        _source("medium", MEDIUM_BASE_URL),
        tag="engineering",
        limit=1,
    )

    assert errors == []
    assert captured["url"] == "https://medium.com/feed/tag/engineering"
    assert items[0].title == "Engineering Post"


def test_community_url_builders() -> None:
    assert build_lobsters_url(LOBSTERS_BASE_URL, tag="ai") == "https://lobste.rs/t/ai.json"
    assert build_stackoverflow_questions_url(
        STACKOVERFLOW_API_URL,
        tagged="python",
        site="stackoverflow",
        limit=2,
    ) == (
        "https://api.stackexchange.com/2.3/questions?"
        "order=desc&sort=activity&tagged=python&site=stackoverflow&pagesize=2"
    )
    assert build_devto_articles_url(DEVTO_API_URL, tag="ai", limit=2) == (
        "https://dev.to/api/articles?per_page=2&tag=ai"
    )
    assert build_medium_feed_url(MEDIUM_BASE_URL, tag="engineering") == (
        "https://medium.com/feed/tag/engineering"
    )


def _source(source_type: str, url: str, metadata=None) -> SourceDefinition:
    return SourceDefinition(
        source_id=f"{source_type}-source",
        name=f"{source_type} Source",
        source_type=source_type,
        url=url,
        reliability="medium",
        topics=["AI"],
        language="en",
        metadata=metadata or {},
    )
