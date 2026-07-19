from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from business.foundation.models.source import SourceDefinition
from infrastructure.external.sources import (
    ARXIV_API_URL,
    ArxivConnector,
    ArxivSourceConnector,
    DomainRateLimiter,
    RobotsDisallowedError,
    SourceFetchPolicy,
)
from infrastructure.external.sources.fetch_policy import fetch_attempts


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
    <link href="http://arxiv.org/pdf/2605.00001v1" rel="related" type="application/pdf" title="pdf"/>
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
    assert item.metadata["pdf_url"] == "https://arxiv.org/pdf/2605.00001v1.pdf"
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


def test_arxiv_connector_fetch_accepts_explicit_runtime_query() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return ARXIV_FIXTURE

    items, errors = ArxivConnector(fetch_text=fetch_text).fetch(
        _source(metadata={}),
        query="cat:cs.LG",
        limit=1,
    )

    assert errors == []
    assert len(items) == 1
    assert captured["url"].startswith(f"{ARXIV_API_URL}?")
    assert "search_query=cat%3Acs.LG" in captured["url"]


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


@pytest.mark.parametrize(
    ("method_name", "content_type", "body"),
    [
        ("fetch_source_package", "application/gzip", b"source archive"),
        ("fetch_pdf_package", "application/pdf", b"%PDF-1.7\nsource"),
    ],
)
def test_arxiv_package_fetch_retries_robots_transport_failure(
    monkeypatch,
    method_name: str,
    content_type: str,
    body: bytes,
) -> None:
    robots_calls = 0
    fetch_calls = 0

    class CountingRateLimiter:
        def __init__(self) -> None:
            self.delegate = DomainRateLimiter()
            self.calls = 0

        def reserve(self, url: str, *, limit_per_minute: int | None):
            self.calls += 1
            return self.delegate.reserve(
                url,
                limit_per_minute=limit_per_minute,
            )

    limiter = CountingRateLimiter()

    class Headers:
        def get_content_type(self):
            return content_type

        def get(self, _name, default=None):
            return default

        def items(self):
            return []

    class Response:
        status = 200
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def geturl(self):
            return "https://arxiv.org/result"

        def read(self, _size):
            return body

    def ensure_robots(_url, _policy):
        nonlocal robots_calls
        robots_calls += 1
        if robots_calls == 1:
            raise HTTPError(
                "https://arxiv.org/robots.txt",
                503,
                "temporarily unavailable",
                hdrs=None,
                fp=None,
            )

    def open_request(_request, _policy):
        nonlocal fetch_calls
        fetch_calls += 1
        return Response()

    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.ensure_robots_allowed",
        ensure_robots,
    )
    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.open_request_with_fetch_policy",
        open_request,
    )
    connector = ArxivSourceConnector(
        fetch_policy=SourceFetchPolicy(
            respect_robots=True,
            retry_times=1,
            retry_on_status_codes=(503,),
        ),
        rate_limiter=limiter,
    )

    package = getattr(connector, method_name)("2607.00001")

    assert package.content == body
    assert limiter.calls == 1
    assert robots_calls == 2
    assert fetch_calls == 1


@pytest.mark.parametrize("method_name", ["fetch_source_package", "fetch_pdf_package"])
def test_arxiv_package_fetch_does_not_retry_robots_denial(
    monkeypatch,
    method_name: str,
) -> None:
    robots_calls = 0
    fetch_calls = 0

    def deny_robots(url, policy):
        nonlocal robots_calls
        robots_calls += 1
        raise RobotsDisallowedError(
            url,
            "https://arxiv.org/robots.txt",
            policy.user_agent,
        )

    def open_request(_request, _policy):
        nonlocal fetch_calls
        fetch_calls += 1
        raise AssertionError("content fetch must not run after robots denial")

    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.ensure_robots_allowed",
        deny_robots,
    )
    monkeypatch.setattr(
        "infrastructure.external.sources.arxiv.open_request_with_fetch_policy",
        open_request,
    )
    connector = ArxivSourceConnector(
        fetch_policy=SourceFetchPolicy(respect_robots=True, retry_times=3)
    )

    with pytest.raises(RobotsDisallowedError) as captured:
        getattr(connector, method_name)("2607.00001")

    assert fetch_attempts(captured.value) == 1
    assert robots_calls == 1
    assert fetch_calls == 0


def _source(*, metadata: dict[str, object] | None = None) -> SourceDefinition:
    return SourceDefinition(
        source_id="arxiv",
        name="arXiv",
        source_type="arxiv",
        url=ARXIV_API_URL,
        reliability="high",
        authority_score=0.95,
        language="en",
        metadata=metadata or {},
    )
