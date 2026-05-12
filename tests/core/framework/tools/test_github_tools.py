import json

from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_github_tools,
)
from sources.connectors import GITHUB_API_URL, GithubConnector


GITHUB_RELEASES = json.dumps(
    [
        {
            "id": 1,
            "url": "https://api.github.com/repos/owner/repo/releases/1",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
            "tag_name": "v1.0.0",
            "target_commitish": "main",
            "name": "Version 1.0.0",
            "body": "Release notes for version 1.",
            "draft": False,
            "prerelease": False,
            "created_at": "2026-05-10T10:00:00Z",
            "published_at": "2026-05-11T12:00:00Z",
            "author": {"login": "maintainer"},
        }
    ]
)


def test_github_fetch_releases_tool_returns_parsed_releases() -> None:
    captured = {}

    def fetch_text(url: str) -> str:
        captured["url"] = url
        return GITHUB_RELEASES

    registry = ToolRegistry()
    register_github_tools(registry, connector=GithubConnector(fetch_text=fetch_text))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="github.fetch_releases",
            arguments={"repository": "owner/repo", "limit": 1},
        ),
        ToolPolicy(allowed_tools=["github.fetch_releases"]),
    )

    item = observation.result.output["items"][0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert captured["url"] == f"{GITHUB_API_URL}/repos/owner/repo/releases?per_page=1"
    assert observation.result.output["repository"] == "owner/repo"
    assert observation.result.output["item_count"] == 1
    assert observation.result.output["error_count"] == 0
    assert item["title"] == "Version 1.0.0"
    assert item["source_type"] == "github"
    assert item["metadata"]["repository"] == "owner/repo"
    assert item["metadata"]["tag_name"] == "v1.0.0"


def test_github_fetch_releases_tool_returns_connector_errors() -> None:
    registry = ToolRegistry()
    register_github_tools(registry, connector=GithubConnector(fetch_text=lambda url: "[]"))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="github.fetch_releases",
            arguments={"repository": "owner/repo", "limit": 1},
        ),
        ToolPolicy(allowed_tools=["github.fetch_releases"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output["item_count"] == 0
    assert observation.result.output["error_count"] == 1
    assert observation.result.output["errors"][0]["error_type"] == "empty_github_releases"


def test_github_fetch_releases_tool_rejects_blank_repository() -> None:
    registry = ToolRegistry()
    register_github_tools(registry, connector=GithubConnector(fetch_text=lambda url: GITHUB_RELEASES))
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(tool_name="github.fetch_releases", arguments={"repository": " "}),
        ToolPolicy(allowed_tools=["github.fetch_releases"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "repository is required" in (observation.result.error_message or "")
