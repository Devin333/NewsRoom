from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_source_tools,
)


RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example RSS</title>
    <item>
      <title>Chip Export Update</title>
      <link>https://example.com/news/chips?utm_source=newsletter</link>
      <description>New export controls were announced.</description>
      <pubDate>Mon, 11 May 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_source_parse_rss_tool_uses_feed_connector_through_executor() -> None:
    registry = ToolRegistry()
    register_source_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.parse_rss",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                    "reliability": "high",
                    "authority_score": 0.9,
                },
                "xml": RSS_FIXTURE,
                "limit": 1,
            },
        ),
        ToolPolicy(allowed_tools=["source.parse_rss"]),
    )

    item = observation.result.output["items"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 1
    assert item["title"] == "Chip Export Update"
    assert item["source_id"] == "rss-example"
    assert item["metadata"]["source_reliability"] == "high"


def test_source_normalize_url_tool_removes_tracking_parameters() -> None:
    registry = ToolRegistry()
    register_source_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.normalize_url",
            arguments={"url": "HTTPS://Example.com/News/?utm_source=x&b=2&a=1#g"},
        ),
        ToolPolicy(allowed_tools=["source.normalize_url"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["canonical_url"] == "https://example.com/News?a=1&b=2"
