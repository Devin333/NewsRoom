from __future__ import annotations

from domain.sources import SourceDefinition


def fixture_source() -> SourceDefinition:
    return SourceDefinition(
        source_id="fixture-ai",
        name="Fixture AI Feed",
        source_type="rss",
        url="fixture://ai",
        reliability="high",
        topics=["ai", "chips", "policy"],
    )


def fixture_feed() -> str:
    return """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Fixture AI</title>
    <item>
      <title>AI chip policy update</title>
      <link>https://example.com/ai-chip-policy</link>
      <description>Export controls and model supply chains remain central.</description>
      <pubDate>Mon, 11 May 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>New model evaluation benchmark</title>
      <link>https://example.com/model-benchmark</link>
      <description>Researchers published a deterministic evaluation benchmark.</description>
      <pubDate>Mon, 11 May 2026 01:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
