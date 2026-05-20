from datetime import UTC, datetime

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources import ARXIV_API_URL, ArxivConnector, SourceFetchPolicy


ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2605.00001v1</id>
    <updated>2026-05-11T12:00:00Z</updated>
    <published>2026-05-10T10:00:00Z</published>
    <title> Agent Runtime Evaluation </title>
    <summary>
      We evaluate agent runtime systems.
    </summary>
    <author><name>Alice Example</name></author>
    <author><name>Bob Example</name></author>
    <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2605.00001v1" rel="alternate" type="text/html"/>
    <arxiv:comment>12 pages</arxiv:comment>
    <arxiv:doi>10.0000/example</arxiv:doi>
  </entry>
</feed>
"""


def test_arxiv_connector_parses_atom_entries() -> None:
    source = _source()

    items = ArxivConnector().parse(source, ARXIV_FIXTURE)

    assert len(items) == 1
    item = items[0]
    assert item.source_type.value == "arxiv"
    assert item.title == "Agent Runtime Evaluation"
    assert item.url == "http://arxiv.org/abs/2605.00001v1"
    assert item.published_at == datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    assert item.authors == ["Alice Example", "Bob Example"]
    assert item.tags == ["cs.AI", "cs.LG"]
    assert item.metadata["arxiv_id"] == "2605.00001v1"
    assert item.metadata["primary_category"] == "cs.AI"
    assert item.metadata["doi"] == "10.0000/example"
    assert item.metadata["comment"] == "12 pages"


def test_arxiv_connector_fetch_builds_query_url() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return ARXIV_FIXTURE

    items, errors = ArxivConnector(fetch_text=fetch_text).fetch(
        _source(),
        query="cat:cs.AI",
        limit=1,
    )

    assert errors == []
    assert len(items) == 1
    assert captured["url"].startswith(f"{ARXIV_API_URL}?")
    assert "search_query=cat%3Acs.AI" in captured["url"]
    assert "max_results=1" in captured["url"]
    assert "sortBy=submittedDate" in captured["url"]


def test_arxiv_connector_returns_empty_feed_error() -> None:
    xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" />"""

    items, errors = ArxivConnector(fetch_text=lambda url: xml).fetch(
        _source(),
        query="cat:cs.AI",
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "empty_arxiv_feed"
    assert errors[0].metadata["phase"] == "parse"


def test_arxiv_connector_returns_invalid_query_error() -> None:
    items, errors = ArxivConnector(fetch_text=lambda url: ARXIV_FIXTURE).fetch(_source(), query=" ")

    assert items == []
    assert errors[0].error_type == "invalid_source_config"
    assert errors[0].metadata["phase"] == "fetch"


def test_arxiv_connector_default_fetch_rejects_unsupported_content_type(monkeypatch) -> None:
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
            return ARXIV_FIXTURE.encode("utf-8")

    def fake_open_request(request, policy):
        return Response()

    monkeypatch.setattr("infrastructure.external.sources.arxiv.open_request_with_fetch_policy", fake_open_request)

    items, errors = ArxivConnector(fetch_policy=SourceFetchPolicy(respect_robots=False)).fetch(
        _source(),
        query="cat:cs.AI",
        limit=1,
    )

    assert items == []
    assert errors[0].error_type == "unsupported_content_type"
    assert errors[0].metadata["phase"] == "fetch"
    assert errors[0].metadata["content_type"] == "text/html"
    assert errors[0].metadata["retryable"] is False
    assert errors[0].metadata["source_health_affecting"] is False
    assert "application/atom+xml" in errors[0].metadata["supported_content_types"]


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="arxiv",
        name="arXiv",
        source_type="arxiv",
        url=ARXIV_API_URL,
        reliability="high",
        authority_score=0.95,
        language="en",
    )
