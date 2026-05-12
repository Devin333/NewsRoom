from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from domain.sources import SourceDefinition
from sources.connectors import DomainRateLimiter, FeedConnector, SourceFetchPolicy


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example RSS</title>
    <item>
      <title>AI chip export update</title>
      <link>https://example.com/articles/chips?utm_source=x</link>
      <description>Policy update summary.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


ATOM_FIXTURE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <entry>
    <title>Model release notes</title>
    <link href="https://example.com/releases/model" />
    <summary>Release summary.</summary>
    <updated>2026-05-11T02:00:00Z</updated>
  </entry>
</feed>
"""


def test_feed_connector_parses_rss_fixture() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
        reliability="high",
    )

    items = FeedConnector().parse(source, RSS_FIXTURE)

    assert len(items) == 1
    assert items[0].title == "AI chip export update"
    assert items[0].url == "https://example.com/articles/chips?utm_source=x"
    assert items[0].metadata["source_reliability"] == "high"
    assert items[0].metadata["source_authority_score"] == 0.5


def test_feed_connector_parses_atom_fixture() -> None:
    source = SourceDefinition(
        source_id="atom-source",
        name="Atom Source",
        source_type="atom",
        url="https://example.com/atom.xml",
    )

    items = FeedConnector().parse(source, ATOM_FIXTURE)

    assert len(items) == 1
    assert items[0].title == "Model release notes"
    assert items[0].url == "https://example.com/releases/model"


def test_feed_connector_fetch_returns_structured_error() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(fetch_text=lambda url: (_ for _ in ()).throw(RuntimeError("boom")))

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].source_id == "rss-source"
    assert errors[0].error_type == "fetch_connection_error"
    assert errors[0].metadata["original_exception_type"] == "RuntimeError"
    assert errors[0].metadata["retryable"] is True


def test_feed_connector_fetch_returns_empty_response_error() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(fetch_text=lambda url: "  \n")

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "empty_source_response"
    assert errors[0].url == "https://example.com/rss.xml"
    assert errors[0].metadata["phase"] == "fetch"


def test_feed_connector_fetch_returns_empty_feed_error() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(
        fetch_text=lambda url: """<?xml version="1.0"?><rss version="2.0"><channel /></rss>"""
    )

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "empty_feed"
    assert errors[0].metadata["phase"] == "parse"


def test_feed_connector_fetch_maps_parse_error() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(fetch_text=lambda url: "<rss")

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "parse_error"
    assert errors[0].metadata["phase"] == "parse"
    assert errors[0].metadata["retryable"] is False


def test_feed_connector_fetch_maps_timeout_error() -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(fetch_text=lambda url: (_ for _ in ()).throw(URLError(TimeoutError("timed out"))))

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "fetch_timeout"
    assert errors[0].metadata["original_exception_type"] == "URLError"
    assert errors[0].metadata["retryable"] is True


@pytest.mark.parametrize(
    ("status_code", "expected_error_type", "expected_retryable"),
    [(404, "fetch_http_4xx", False), (429, "fetch_http_4xx", True), (503, "fetch_http_5xx", True)],
)
def test_feed_connector_fetch_maps_http_errors(
    status_code: int,
    expected_error_type: str,
    expected_retryable: bool,
) -> None:
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(
        fetch_text=lambda url: (_ for _ in ()).throw(
            HTTPError(url, status_code, "http error", hdrs=None, fp=BytesIO(b""))
        )
    )

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == expected_error_type
    assert errors[0].metadata["status_code"] == status_code
    assert errors[0].metadata["retryable"] is expected_retryable


def test_feed_connector_default_fetch_applies_policy(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            captured["read_size"] = size
            return b"abcdef"

    def fake_urlopen(request, timeout):
        captured["user_agent"] = request.headers["User-agent"]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("sources.connectors.feed.urlopen", fake_urlopen)
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(
        fetch_policy=SourceFetchPolicy(timeout_seconds=3, max_bytes=5, user_agent="NewsRoomTest/1.0")
    )

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "max_bytes_exceeded"
    assert "max_bytes" in errors[0].error_message
    assert captured == {
        "user_agent": "NewsRoomTest/1.0",
        "timeout": 3,
        "read_size": 6,
    }


def test_feed_connector_retries_transient_fetch_error() -> None:
    calls = []
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )

    def fetch_text(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            raise HTTPError(url, 503, "unavailable", hdrs=None, fp=BytesIO(b""))
        return RSS_FIXTURE

    connector = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=SourceFetchPolicy(retry_times=1),
    )

    items, errors = connector.fetch(source)

    assert len(items) == 1
    assert errors == []
    assert calls == ["https://example.com/rss.xml", "https://example.com/rss.xml"]


def test_feed_connector_does_not_retry_unconfigured_http_4xx() -> None:
    calls = []
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )

    def fetch_text(url: str) -> str:
        calls.append(url)
        raise HTTPError(url, 404, "missing", hdrs=None, fp=BytesIO(b""))

    connector = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=SourceFetchPolicy(retry_times=2),
    )

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "fetch_http_4xx"
    assert errors[0].metadata["attempts"] == 1
    assert calls == ["https://example.com/rss.xml"]


def test_feed_connector_reports_attempts_after_retry_exhaustion() -> None:
    calls = []
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )

    def fetch_text(url: str) -> str:
        calls.append(url)
        raise HTTPError(url, 503, "unavailable", hdrs=None, fp=BytesIO(b""))

    connector = FeedConnector(
        fetch_text=fetch_text,
        fetch_policy=SourceFetchPolicy(retry_times=2),
    )

    items, errors = connector.fetch(source)

    assert items == []
    assert errors[0].error_type == "fetch_http_5xx"
    assert errors[0].metadata["attempts"] == 3
    assert errors[0].metadata["retryable"] is True
    assert calls == [
        "https://example.com/rss.xml",
        "https://example.com/rss.xml",
        "https://example.com/rss.xml",
    ]


def test_feed_connector_rate_limits_same_domain_before_fetch() -> None:
    calls = []
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    same_domain = SourceDefinition(
        source_id="rss-source-2",
        name="RSS Source 2",
        source_type="rss",
        url="https://example.com/other.xml",
    )
    connector = FeedConnector(
        fetch_text=lambda url: calls.append(url) or RSS_FIXTURE,
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
        rate_limiter=DomainRateLimiter(now=lambda: datetime(2026, 5, 11, tzinfo=UTC)),
    )

    first_items, first_errors = connector.fetch(source)
    second_items, second_errors = connector.fetch(same_domain)

    assert len(first_items) == 1
    assert first_errors == []
    assert second_items == []
    assert second_errors[0].error_type == "rate_limited"
    assert second_errors[0].url == "https://example.com/other.xml"
    assert second_errors[0].metadata["domain"] == "example.com"
    assert second_errors[0].metadata["retryable"] is True
    assert second_errors[0].metadata["source_health_affecting"] is False
    assert calls == ["https://example.com/rss.xml"]


def test_feed_connector_rate_limit_is_per_domain() -> None:
    calls = []
    now = datetime(2026, 5, 11, tzinfo=UTC)
    connector = FeedConnector(
        fetch_text=lambda url: calls.append(url) or RSS_FIXTURE,
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
        rate_limiter=DomainRateLimiter(now=lambda: now),
    )
    first = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    other = SourceDefinition(
        source_id="rss-other",
        name="Other RSS",
        source_type="rss",
        url="https://other.example/rss.xml",
    )

    first_items, first_errors = connector.fetch(first)
    other_items, other_errors = connector.fetch(other)

    assert len(first_items) == 1
    assert first_errors == []
    assert len(other_items) == 1
    assert other_errors == []
    assert calls == ["https://example.com/rss.xml", "https://other.example/rss.xml"]


def test_feed_connector_rate_limit_window_resets() -> None:
    calls = []
    clock = {"now": datetime(2026, 5, 11, tzinfo=UTC)}
    source = SourceDefinition(
        source_id="rss-source",
        name="RSS Source",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    connector = FeedConnector(
        fetch_text=lambda url: calls.append(url) or RSS_FIXTURE,
        fetch_policy=SourceFetchPolicy(rate_limit_per_domain_per_minute=1),
        rate_limiter=DomainRateLimiter(now=lambda: clock["now"]),
    )

    first_items, first_errors = connector.fetch(source)
    blocked_items, blocked_errors = connector.fetch(source)
    clock["now"] = clock["now"] + timedelta(seconds=61)
    reset_items, reset_errors = connector.fetch(source)

    assert len(first_items) == 1
    assert first_errors == []
    assert blocked_items == []
    assert blocked_errors[0].error_type == "rate_limited"
    assert len(reset_items) == 1
    assert reset_errors == []
    assert calls == ["https://example.com/rss.xml", "https://example.com/rss.xml"]


def test_source_fetch_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        SourceFetchPolicy(timeout_seconds=0)
    with pytest.raises(ValueError, match="max_bytes"):
        SourceFetchPolicy(max_bytes=0)
    with pytest.raises(ValueError, match="user_agent"):
        SourceFetchPolicy(user_agent="")
    with pytest.raises(ValueError, match="rate_limit_per_domain_per_minute"):
        SourceFetchPolicy(rate_limit_per_domain_per_minute=0)
    with pytest.raises(ValueError, match="retry_times"):
        SourceFetchPolicy(retry_times=-1)
    with pytest.raises(ValueError, match="retry_on_status_codes"):
        SourceFetchPolicy(retry_on_status_codes=(99,))
