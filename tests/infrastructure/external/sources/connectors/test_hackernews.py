import json
from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources.hackernews import (
    HACKERNEWS_API_URL,
    HackerNewsConnector,
    build_hackernews_item_url,
    build_hackernews_story_list_url,
)


HACKERNEWS_ITEM = json.dumps(
    {
        "id": 123,
        "type": "story",
        "by": "pg",
        "time": 1778490000,
        "title": "AI policy update",
        "url": "https://example.com/ai-policy",
        "text": "<p>Policy summary.</p>",
        "score": 42,
        "descendants": 5,
    }
)


def test_hackernews_connector_parses_story_item() -> None:
    item = HackerNewsConnector().parse_item(_source(), HACKERNEWS_ITEM, story_list="topstories")

    assert item is not None
    assert item.source_type.value == "hackernews"
    assert item.title == "AI policy update"
    assert item.url == "https://example.com/ai-policy"
    assert item.published_at == datetime(2026, 5, 11, 9, 0, tzinfo=UTC)
    assert item.summary == "Policy summary."
    assert item.authors == ["pg"]
    assert item.tags == ["topstories", "story"]
    assert item.metadata["hackernews_item_id"] == 123
    assert item.metadata["discussion_url"] == "https://news.ycombinator.com/item?id=123"
    assert item.metadata["score"] == 42
    assert item.metadata["comments_count"] == 5


def test_hackernews_connector_fetches_story_list_and_items() -> None:
    captured = []

    def fetch_text(url: str) -> str:
        captured.append(url)
        if url.endswith("/topstories.json"):
            return "[123]"
        return HACKERNEWS_ITEM

    items, errors = HackerNewsConnector(fetch_text=fetch_text).fetch(
        _source(),
        story_list="topstories",
        limit=1,
    )

    assert errors == []
    assert len(items) == 1
    assert captured == [
        build_hackernews_story_list_url(HACKERNEWS_API_URL, "topstories"),
        build_hackernews_item_url(HACKERNEWS_API_URL, 123),
    ]


def test_hackernews_connector_returns_invalid_story_list_error() -> None:
    items, errors = HackerNewsConnector(fetch_text=lambda url: "[123]").fetch(
        _source(story_list="badstories"),
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].retryable is False


def test_hackernews_connector_returns_empty_items_error() -> None:
    items, errors = HackerNewsConnector(fetch_text=lambda url: "[]").fetch(
        _source(),
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "empty_hackernews_story_ids"
    assert errors[0].metadata["phase"] == "parse"


def test_hackernews_connector_default_fetch_rejects_unsupported_content_type(monkeypatch) -> None:
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
            return b"[123]"

    def fake_open_request(request, policy):
        return Response()

    monkeypatch.setattr("infrastructure.external.sources.hackernews.open_request_with_fetch_policy", fake_open_request)

    items, errors = HackerNewsConnector().fetch(_source(respect_robots=False), limit=1)

    assert items == []
    assert errors[0].error_type == "unsupported_content_type"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].metadata["content_type"] == "text/html"


def _source(*, story_list: str = "topstories", respect_robots: bool = True) -> SourceDefinition:
    return SourceDefinition(
        source_id="hackernews",
        name="Hacker News",
        source_type="hackernews",
        url=HACKERNEWS_API_URL,
        reliability="medium",
        authority_score=0.75,
        respect_robots=respect_robots,
        topics=["ai", "technology"],
        language="en",
        metadata={"story_list": story_list},
    )
