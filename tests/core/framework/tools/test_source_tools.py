from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_source_tools,
)
from sources.connectors import SourceFetchPolicy


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


def test_source_fetch_url_tool_fetches_configured_source_through_executor() -> None:
    registry = ToolRegistry()
    seen_urls: list[str] = []
    register_source_tools(
        registry,
        fetch_text=lambda url: seen_urls.append(url) or "source content",
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml?utm_source=x&b=2&a=1",
                    "source_type": "rss",
                    "reliability": "high",
                },
                "max_bytes": 100,
                "timeout_seconds": 2,
                "user_agent": "NewsRoomTest/1.0",
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert seen_urls == ["https://example.com/feed.xml?utm_source=x&b=2&a=1"]
    assert observation.result.output["source_id"] == "rss-example"
    assert observation.result.output["content"] == "source content"
    assert observation.result.output["content_bytes"] == len("source content")
    assert observation.result.output["canonical_url"] == "https://example.com/feed.xml?a=1&b=2"
    assert observation.result.output["fetch_policy"] == {
        "timeout_seconds": 2.0,
        "max_bytes": 100,
        "user_agent": "NewsRoomTest/1.0",
    }


def test_source_fetch_url_tool_rejects_non_http_urls_before_fetch() -> None:
    registry = ToolRegistry()
    calls = {"count": 0}
    register_source_tools(
        registry,
        fetch_text=lambda url: calls.__setitem__("count", calls["count"] + 1) or "content",
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "local",
                    "name": "Local",
                    "url": "file:///etc/passwd",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "only supports http and https" in (observation.result.error_message or "")


def test_source_fetch_url_tool_applies_max_bytes_to_injected_fetcher() -> None:
    registry = ToolRegistry()
    register_source_tools(registry, fetch_text=lambda url: "abcdef")
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                },
                "max_bytes": 5,
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "max_bytes" in (observation.result.error_message or "")


def test_source_fetch_url_tool_default_fetch_uses_source_fetch_policy(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        class Headers:
            def get_content_type(self):
                return "application/rss+xml"

        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            captured["read_size"] = size
            return b"abc"

    def fake_urlopen(request, timeout):
        captured["user_agent"] = request.headers["User-agent"]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("core.framework.tools.source_tools.urlopen", fake_urlopen)
    registry = ToolRegistry()
    register_source_tools(
        registry,
        fetch_policy=SourceFetchPolicy(
            timeout_seconds=3,
            max_bytes=5,
            user_agent="NewsRoomTest/1.0",
        ),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["content"] == "abc"
    assert observation.result.output["status_code"] == 200
    assert observation.result.output["content_type"] == "application/rss+xml"
    assert captured == {
        "user_agent": "NewsRoomTest/1.0",
        "timeout": 3,
        "read_size": 6,
    }


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
