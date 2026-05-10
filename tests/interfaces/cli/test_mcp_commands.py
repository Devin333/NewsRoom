import json

import interfaces.cli.news as news_cli


def test_news_cli_mcp_catalog_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(["mcp", "catalog", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["tools"][0]["name"] == "news.source.health"


def test_news_cli_mcp_call_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(
        [
            "mcp",
            "call",
            "news.source.health",
            "--args-json",
            "{\"include_disabled\": true}",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["tool_name"] == "news.source.health"
    assert payload["success"] is True
    assert payload["data"]["source_count"] == 1


class _FakeMCPService:
    def catalog(self):
        return _FakeResult(
            {
                "tools": [
                    {
                        "name": "news.source.health",
                        "title": "Read source health",
                        "description": "Read source health.",
                        "input_schema": {},
                    }
                ],
                "resources": [],
                "prompts": [],
            }
        )

    def call_tool(self, tool_name, arguments):
        return _FakeToolResult(
            {
                "tool_name": tool_name,
                "success": True,
                "data": {"source_count": 1, "arguments": arguments},
                "error_type": None,
                "error_message": None,
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeToolResult(_FakeResult):
    @property
    def success(self):
        return self.payload["success"]
