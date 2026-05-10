from domain.sources import SourceDefinition
from sources.connectors import FeedConnector


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
    assert errors[0].error_type == "RuntimeError"
