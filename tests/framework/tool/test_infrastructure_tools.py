from __future__ import annotations

from framework.tool import ToolCall, ToolExecutor, ToolPolicy, ToolRegistry, ToolStatus
from infrastructure.tools import WebSearchResult, register_web_search_tools


def test_web_search_tool_lives_in_infrastructure() -> None:
    registry = ToolRegistry()
    register_web_search_tools(registry, provider=_Provider())

    observation = ToolExecutor(registry).execute(
        ToolCall(tool_name="web.search", arguments={"query": "agent memory"}),
        ToolPolicy(allowed_tools=["web.search"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["results"][0]["title"] == "Agent Memory"


class _Provider:
    def search(self, *, query: str, limit: int, timeout_seconds: float):
        return [WebSearchResult(title="Agent Memory", url="https://example.com")]
