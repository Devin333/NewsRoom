from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError

from domain.sources import SourceDefinition
from sources.connectors import HtmlConnector, SourceFetchPolicy, extract_html


HTML_FIXTURE = """<!doctype html>
<html lang="en">
  <head>
    <title> Product Launch Notes </title>
    <link rel="canonical" href="https://example.com/blog/product-launch" />
    <meta name="description" content="Launch summary for the new product." />
    <meta property="article:published_time" content="2026-05-11T10:30:00Z" />
    <meta name="author" content="Alice Example; Bob Example" />
  </head>
  <body>
    <nav>Ignore navigation links</nav>
    <article>
      <h1>Product Launch Notes</h1>
      <p>The product launch introduces a production workflow for source processing.</p>
      <p>It includes extraction confidence, canonical URLs, and metadata capture.</p>
    </article>
    <footer>Ignore footer</footer>
  </body>
</html>
"""


def test_extract_html_returns_metadata_and_visible_text() -> None:
    result = extract_html(HTML_FIXTURE)

    assert result.title == "Product Launch Notes"
    assert result.canonical_url == "https://example.com/blog/product-launch"
    assert result.summary == "Launch summary for the new product."
    assert result.published_at == datetime(2026, 5, 11, 10, 30, tzinfo=UTC)
    assert result.authors == ["Alice Example", "Bob Example"]
    assert result.language == "en"
    assert "production workflow" in (result.text or "")
    assert "Ignore navigation" not in (result.text or "")
    assert result.confidence >= 0.9


def test_html_connector_parses_html_into_raw_source_item() -> None:
    source = _source()

    items = HtmlConnector().parse(source, HTML_FIXTURE)

    assert len(items) == 1
    item = items[0]
    assert item.source_type.value == "html"
    assert item.title == "Product Launch Notes"
    assert item.url == "https://example.com/blog/product-launch"
    assert item.published_at == datetime(2026, 5, 11, 10, 30, tzinfo=UTC)
    assert item.authors == ["Alice Example", "Bob Example"]
    assert item.language == "en"
    assert "canonical URLs" in (item.raw_content or "")
    assert item.metadata["extractor_name"] == "stdlib_html_extractor"
    assert item.metadata["extraction_confidence"] >= 0.9
    assert item.metadata["source_reliability"] == "high"


def test_html_connector_falls_back_to_source_name_and_url_for_minimal_html() -> None:
    source = _source()
    html = "<html><body><p>Only visible body text is available here.</p></body></html>"

    items = HtmlConnector().parse(source, html)

    assert len(items) == 1
    assert items[0].title == "Example Blog"
    assert items[0].url == "https://example.com/blog/product-launch"
    assert items[0].summary == "Only visible body text is available here."
    assert items[0].metadata["extraction_confidence"] > 0


def test_html_connector_normalizes_relative_canonical_url() -> None:
    source = SourceDefinition(
        source_id="blog",
        name="Example Blog",
        source_type="html",
        url="https://Example.com/blog/index.html",
    )
    html = """<html><head>
      <title>Relative Canonical</title>
      <link rel="canonical" href="/blog/post?utm_source=x" />
    </head><body><p>Body text for a relative canonical page.</p></body></html>"""

    items = HtmlConnector().parse(source, html)

    assert len(items) == 1
    assert items[0].url == "https://example.com/blog/post"
    assert items[0].metadata["canonical_url"] == "https://example.com/blog/post"


def test_html_connector_fetch_retries_transient_failure() -> None:
    calls = []

    def fetch_text(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            raise HTTPError(url, 503, "unavailable", hdrs=None, fp=BytesIO(b""))
        return HTML_FIXTURE

    items, errors = HtmlConnector(
        fetch_text=fetch_text,
        fetch_policy=SourceFetchPolicy(retry_times=1),
    ).fetch(_source())

    assert len(items) == 1
    assert errors == []
    assert calls == [
        "https://example.com/blog/product-launch",
        "https://example.com/blog/product-launch",
    ]


def test_html_connector_fetch_returns_empty_response_error() -> None:
    items, errors = HtmlConnector(fetch_text=lambda url: "  \n").fetch(_source())

    assert items == []
    assert errors[0].error_type == "empty_source_response"
    assert errors[0].metadata["phase"] == "fetch"


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="blog",
        name="Example Blog",
        source_type="html",
        url="https://example.com/blog/product-launch",
        reliability="high",
        authority_score=0.8,
    )
