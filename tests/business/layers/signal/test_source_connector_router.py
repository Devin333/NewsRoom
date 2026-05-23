from datetime import UTC, datetime

import pytest

from business.foundation.models.source import SourceDefinition
from business.layers.signal.source_router import SourceConnectorRouter
from infrastructure.external.sources.models import RawSourceItem, SourceError


def test_source_connector_router_routes_feed_types_to_feed_connector() -> None:
    feed = _FakeConnector()
    router = SourceConnectorRouter(feed_connector=feed)
    source = SourceDefinition(
        source_id="openai-news",
        name="OpenAI News",
        source_type="official_blog",
        url="https://example.com/rss.xml",
    )

    items, errors = router.fetch(source, limit=2)

    assert errors == []
    assert len(items) == 1
    assert feed.calls == [("official_blog", 2, None)]


def test_source_connector_router_routes_arxiv_query() -> None:
    arxiv = _FakeConnector()
    router = SourceConnectorRouter(arxiv_connector=arxiv)
    source = SourceDefinition(
        source_id="arxiv",
        name="arXiv",
        source_type="arxiv",
        url="https://export.arxiv.org/api/query",
        metadata={"query": "cat:cs.AI"},
    )

    router.fetch(source, query="cat:cs.LG", limit=3)

    assert arxiv.calls == [("arxiv", 3, "cat:cs.LG")]


def test_source_connector_router_routes_github_query() -> None:
    github = _FakeConnector()
    router = SourceConnectorRouter(github_connector=github)
    source = SourceDefinition(
        source_id="github",
        name="GitHub",
        source_type="github",
        url="https://api.github.com",
        metadata={"mode": "trending", "query": "topic:llm"},
    )

    router.fetch(source, query="topic:agents", limit=4)

    assert github.calls == [("github", 4, "topic:agents")]


@pytest.mark.parametrize(
    ("source_type", "connector_name"),
    [
        ("hackernews", "hackernews_connector"),
        ("reddit", "reddit_connector"),
        ("lobsters", "lobsters_connector"),
        ("stackoverflow", "stackoverflow_connector"),
        ("devto", "devto_connector"),
        ("medium", "medium_connector"),
        ("html", "html_connector"),
        ("web_page", "html_connector"),
        ("manual", "manual_connector"),
    ],
)
def test_source_connector_router_routes_supported_types(source_type: str, connector_name: str) -> None:
    fake = _FakeConnector()
    router = SourceConnectorRouter(**{connector_name: fake})
    source = SourceDefinition(
        source_id=f"{source_type}-source",
        name="Source",
        source_type=source_type,
        url="https://example.com/source",
    )

    router.fetch(source, limit=1)

    assert fake.calls == [(source_type, 1, None)]


def test_source_connector_router_returns_connector_errors() -> None:
    router = SourceConnectorRouter(feed_connector=_FakeConnector(errors=True))
    source = SourceDefinition(
        source_id="rss",
        name="RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
    )

    items, errors = router.fetch(source)

    assert items == []
    assert errors[0].error_type == "fake_error"


class _FakeConnector:
    def __init__(self, *, errors: bool = False) -> None:
        self.calls = []
        self.errors = errors

    def fetch(self, source, *, limit=None, query=None):
        self.calls.append((source.source_type.value, limit, query))
        if self.errors:
            return [], [
                SourceError(
                    source_id=source.source_id,
                    source_name=source.name,
                    error_type="fake_error",
                    error_message="fake error",
                    url=source.url,
                )
            ]
        return [
            RawSourceItem(
                source_item_id="raw-fake",
                source_id=source.source_id,
                source_name=source.name,
                source_type=source.source_type,
                title="Fake item",
                url="https://example.com/item",
                fetched_at=datetime(2026, 5, 23, tzinfo=UTC),
            )
        ], []
