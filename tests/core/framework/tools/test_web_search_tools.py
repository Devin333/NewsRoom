import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from framework.tool import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)
from infrastructure.tools import (
    DuckDuckGoHtmlSearchProvider,
    WebSearchResult,
    register_web_search_tools,
)


def test_web_search_tool_returns_parsed_provider_results() -> None:
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"""
                <html><body>
                  <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fai%3Fref%3Dddg">
                    Example &amp; AI
                  </a>
                  <a class="result__snippet">AI policy source &amp; evidence.</a>
                  <a class="result__a" href="https://example.org/other">Other result</a>
                </body></html>
                """
            )

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = DuckDuckGoHtmlSearchProvider(
            endpoint=f"http://127.0.0.1:{server.server_port}/html/",
            allowed_domains=["127.0.0.1"],
        )
        registry = ToolRegistry()
        register_web_search_tools(registry, provider=provider)
        executor = ToolExecutor(registry)

        observation = executor.execute(
            ToolCall(
                tool_name="web.search",
                arguments={"query": "AI regulation", "limit": 1, "timeout_seconds": 2},
            ),
            ToolPolicy(allowed_tools=["web.search"]),
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    query = parse_qs(urlsplit(requests[0]).query)

    assert observation.status == ToolStatus.SUCCEEDED
    assert query["q"] == ["AI regulation"]
    assert observation.result.output == {
        "query": "AI regulation",
        "result_count": 1,
        "results": [
            {
                "title": "Example & AI",
                "url": "https://example.com/ai?ref=ddg",
                "snippet": "AI policy source & evidence.",
                "source": "duckduckgo",
            }
        ],
    }


def test_web_search_tool_rejects_blank_query_before_provider_call() -> None:
    provider = _RecordingWebSearchProvider()
    registry = ToolRegistry()
    register_web_search_tools(registry, provider=provider)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="web.search", arguments={"query": "   "}),
        ToolPolicy(allowed_tools=["web.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert provider.calls == []
    assert "query is required" in (observation.result.error_message or "")


def test_web_search_provider_blocks_disallowed_endpoint_before_fetch() -> None:
    calls = {"count": 0}

    def fetcher(url, timeout_seconds):
        calls["count"] += 1
        return ""

    provider = DuckDuckGoHtmlSearchProvider(
        endpoint="https://outside.test/html/",
        allowed_domains=["example.com"],
        fetcher=fetcher,
    )
    registry = ToolRegistry()
    register_web_search_tools(registry, provider=provider)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="web.search", arguments={"query": "AI"}),
        ToolPolicy(allowed_tools=["web.search"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert calls["count"] == 0
    assert "endpoint host is not in allowed domains" in (
        observation.result.error_message or ""
    )


class _RecordingWebSearchProvider:
    def __init__(self) -> None:
        self.calls = []

    def search(self, *, query, limit, timeout_seconds):
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "timeout_seconds": timeout_seconds,
            }
        )
        return [
            WebSearchResult(
                title="Result",
                url="https://example.com/result",
                snippet="Snippet",
            )
        ]
