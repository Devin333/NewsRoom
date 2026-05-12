from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_source_tools,
)
from domain.sources import SourceError
from sources.connectors import SourceFetchPolicy
from sources.health import BasicSourceHealthManager


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


ATOM_FIXTURE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <entry>
    <title>Model Release Notes</title>
    <link href="https://example.com/releases/model?utm_source=x" />
    <summary>Release summary.</summary>
    <updated>2026-05-11T02:00:00Z</updated>
  </entry>
</feed>
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


def test_source_fetch_url_tool_allows_configured_domain_and_subdomain() -> None:
    registry = ToolRegistry()
    seen_urls: list[str] = []
    register_source_tools(
        registry,
        fetch_text=lambda url: seen_urls.append(url) or "source content",
        allowed_domains=["example.com"],
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://news.example.com/feed.xml",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert seen_urls == ["https://news.example.com/feed.xml"]


def test_source_fetch_url_tool_rejects_domains_outside_allowlist_before_fetch() -> None:
    registry = ToolRegistry()
    calls = {"count": 0}
    register_source_tools(
        registry,
        fetch_text=lambda url: calls.__setitem__("count", calls["count"] + 1) or "content",
        allowed_domains=["example.com"],
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.fetch_url",
            arguments={
                "source": {
                    "source_id": "rss-evil",
                    "name": "Evil RSS",
                    "url": "https://evil.test/feed.xml",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.fetch_url"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "allowed domains" in (observation.result.error_message or "")


def test_source_check_health_tool_reads_health_manager_state() -> None:
    registry = ToolRegistry()
    health_manager = BasicSourceHealthManager()
    health_manager.record_failure(
        "rss-example",
        SourceError(
            source_id="rss-example",
            error_type="TimeoutError",
            error_message="timed out",
            url="https://example.com/feed.xml",
        ),
    )
    register_source_tools(registry, health_manager=health_manager)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.check_health",
            arguments={"source_id": "rss-example"},
        ),
        ToolPolicy(allowed_tools=["source.check_health"]),
    )

    health = observation.result.output["health"]

    assert observation.status == ToolStatus.SUCCEEDED
    assert health["source_id"] == "rss-example"
    assert health["status"] == "degraded"
    assert health["consecutive_failures"] == 1
    assert health["last_error"]["error_type"] == "TimeoutError"


def test_source_probe_tool_records_success_without_returning_content() -> None:
    registry = ToolRegistry()
    health_manager = BasicSourceHealthManager()
    seen_urls: list[str] = []
    register_source_tools(
        registry,
        fetch_text=lambda url: seen_urls.append(url) or "probe body",
        health_manager=health_manager,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.probe",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.probe"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert seen_urls == ["https://example.com/feed.xml"]
    assert observation.result.output["ok"] is True
    assert observation.result.output["content_bytes"] == len("probe body")
    assert "content" not in observation.result.output
    assert observation.result.output["health"]["status"] == "healthy"
    assert health_manager.get("rss-example").last_success_at is not None


def test_source_probe_tool_records_fetch_failure_as_health_failure() -> None:
    registry = ToolRegistry()
    health_manager = BasicSourceHealthManager(failure_threshold=1)

    def failing_fetch(url: str) -> str:
        raise RuntimeError(f"cannot reach {url}")

    register_source_tools(
        registry,
        fetch_text=failing_fetch,
        health_manager=health_manager,
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.probe",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                }
            },
        ),
        ToolPolicy(allowed_tools=["source.probe"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["ok"] is False
    assert observation.result.output["error"]["error_type"] == "RuntimeError"
    assert observation.result.output["health"]["status"] == "cooling_down"
    assert health_manager.get("rss-example").consecutive_failures == 1


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


def test_source_extract_items_tool_extracts_rss_content() -> None:
    registry = ToolRegistry()
    register_source_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.extract_items",
            arguments={
                "source": {
                    "source_id": "rss-example",
                    "name": "Example RSS",
                    "url": "https://example.com/feed.xml",
                    "source_type": "rss",
                    "reliability": "high",
                },
                "content": RSS_FIXTURE,
                "limit": 1,
            },
        ),
        ToolPolicy(allowed_tools=["source.extract_items"]),
    )

    item = observation.result.output["items"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 1
    assert item["title"] == "Chip Export Update"
    assert item["source_id"] == "rss-example"


def test_source_extract_items_tool_extracts_atom_content() -> None:
    registry = ToolRegistry()
    register_source_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="source.extract_items",
            arguments={
                "source": {
                    "source_id": "atom-example",
                    "name": "Example Atom",
                    "url": "https://example.com/atom.xml",
                    "source_type": "atom",
                },
                "content": ATOM_FIXTURE,
            },
        ),
        ToolPolicy(allowed_tools=["source.extract_items"]),
    )

    item = observation.result.output["items"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 1
    assert item["title"] == "Model Release Notes"
    assert item["source_type"] == "atom"


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
