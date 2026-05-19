from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)
from business.boards.paper_radar.tools import register_arxiv_tools
from sources.connectors import ARXIV_API_URL, ArxivConnector


ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2605.00001v1</id>
    <updated>2026-05-11T12:00:00Z</updated>
    <published>2026-05-10T10:00:00Z</published>
    <title> Agent Runtime Evaluation </title>
    <summary>We evaluate agent runtime systems.</summary>
    <author><name>Alice Example</name></author>
    <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2605.00001v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""


def test_arxiv_search_papers_tool_returns_parsed_items() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return ARXIV_FIXTURE

    registry = ToolRegistry()
    register_arxiv_tools(registry, connector=ArxivConnector(fetch_text=fetch_text))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="arxiv.search_papers",
            arguments={"query": "cat:cs.AI", "limit": 1},
        ),
        ToolPolicy(allowed_tools=["arxiv.search_papers"]),
    )

    item = observation.result.output["items"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert captured["url"].startswith(f"{ARXIV_API_URL}?")
    assert "search_query=cat%3Acs.AI" in captured["url"]
    assert observation.result.output["query"] == "cat:cs.AI"
    assert observation.result.output["item_count"] == 1
    assert observation.result.output["error_count"] == 0
    assert item["title"] == "Agent Runtime Evaluation"
    assert item["source_type"] == "arxiv"
    assert item["metadata"]["primary_category"] == "cs.AI"


def test_arxiv_search_papers_tool_returns_connector_errors() -> None:
    registry = ToolRegistry()
    register_arxiv_tools(
        registry,
        connector=ArxivConnector(
            fetch_text=lambda url: """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" />"""
        ),
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="arxiv.search_papers",
            arguments={"query": "cat:cs.AI", "limit": 1},
        ),
        ToolPolicy(allowed_tools=["arxiv.search_papers"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 0
    assert observation.result.output["error_count"] == 1
    assert observation.result.output["errors"][0]["error_type"] == "empty_arxiv_feed"


def test_arxiv_search_papers_tool_rejects_blank_query() -> None:
    registry = ToolRegistry()
    register_arxiv_tools(registry, connector=ArxivConnector(fetch_text=lambda url: ARXIV_FIXTURE))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="arxiv.search_papers", arguments={"query": " "}),
        ToolPolicy(allowed_tools=["arxiv.search_papers"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "query is required" in (observation.result.error_message or "")
