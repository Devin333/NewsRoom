import json
from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources.reddit import REDDIT_BASE_URL, RedditConnector, build_reddit_listing_url


REDDIT_LISTING = json.dumps(
    {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc123",
                        "subreddit": "MachineLearning",
                        "title": "AI policy update",
                        "permalink": "/r/MachineLearning/comments/abc123/ai_policy_update/",
                        "url_overridden_by_dest": "https://example.com/ai-policy",
                        "selftext": "Policy summary.",
                        "author": "researcher",
                        "created_utc": 1778490000,
                        "score": 100,
                        "num_comments": 12,
                        "link_flair_text": "Discussion",
                        "over_18": False,
                        "is_self": False,
                        "stickied": False,
                    },
                }
            ]
        }
    }
)


def test_reddit_connector_parses_listing_posts() -> None:
    items = RedditConnector().parse_listing(
        _source(),
        REDDIT_LISTING,
        subreddit="MachineLearning",
        listing="new",
    )

    assert len(items) == 1
    item = items[0]
    assert item.source_type.value == "reddit"
    assert item.title == "AI policy update"
    assert item.url == "https://example.com/ai-policy"
    assert item.published_at == datetime(2026, 5, 11, 9, 0, tzinfo=UTC)
    assert item.summary == "Policy summary."
    assert item.authors == ["researcher"]
    assert item.tags == ["MachineLearning", "Discussion"]
    assert item.metadata["subreddit"] == "MachineLearning"
    assert item.metadata["listing"] == "new"
    assert item.metadata["permalink"] == (
        "https://www.reddit.com/r/MachineLearning/comments/abc123/ai_policy_update/"
    )
    assert item.metadata["score"] == 100
    assert item.metadata["comments_count"] == 12


def test_reddit_connector_fetch_builds_listing_url() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return REDDIT_LISTING

    items, errors = RedditConnector(fetch_text=fetch_text).fetch(
        _source(),
        subreddit="MachineLearning",
        listing="new",
        limit=1,
    )

    assert errors == []
    assert len(items) == 1
    assert captured["url"] == build_reddit_listing_url(
        REDDIT_BASE_URL,
        "MachineLearning",
        "new",
        limit=1,
    )


def test_reddit_connector_returns_invalid_subreddit_error() -> None:
    items, errors = RedditConnector(fetch_text=lambda url: REDDIT_LISTING).fetch(
        _source(subreddit=""),
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].retryable is False


def test_reddit_connector_returns_empty_posts_error() -> None:
    items, errors = RedditConnector(fetch_text=lambda url: '{"data": {"children": []}}').fetch(
        _source(),
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "empty_reddit_posts"
    assert errors[0].metadata["phase"] == "parse"


def test_reddit_connector_default_fetch_rejects_unsupported_content_type(monkeypatch) -> None:
    class Headers:
        def get_content_type(self):
            return "text/html"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return REDDIT_LISTING.encode("utf-8")

    def fake_open_request(request, policy):
        return Response()

    monkeypatch.setattr("infrastructure.external.sources.reddit.open_request_with_fetch_policy", fake_open_request)

    items, errors = RedditConnector().fetch(_source(respect_robots=False), limit=1)

    assert items == []
    assert errors[0].error_type == "unsupported_content_type"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].metadata["content_type"] == "text/html"


def _source(*, subreddit: str = "MachineLearning", respect_robots: bool = True) -> SourceDefinition:
    return SourceDefinition(
        source_id="reddit",
        name="Reddit MachineLearning",
        source_type="reddit",
        url=REDDIT_BASE_URL,
        reliability="medium",
        authority_score=0.65,
        respect_robots=respect_robots,
        topics=["ai", "machine learning"],
        language="en",
        metadata={"subreddit": subreddit, "listing": "new"},
    )
