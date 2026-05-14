import json

import interfaces.cli.news as news_cli


def test_news_cli_mcp_catalog_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(["mcp", "catalog", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["tools"][0]["name"] == "news.source.health"


def test_news_cli_mcp_capabilities_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(["mcp", "capabilities", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["schema_version"] == "newsroom.mcp_capability_manifest.v1"
    assert payload["boundary"] == "inbound_mcp_server"
    assert payload["version"] == "1.0"
    assert payload["capability_count"] == 1
    assert payload["capabilities"][0]["name"] == "news.source.health"
    assert payload["capabilities"][0]["permission"] == "sources:read"
    assert payload["capabilities"][0]["category"] == "sources"


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


def test_news_cli_mcp_read_resource_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(
        [
            "mcp",
            "read-resource",
            "news://sources/health",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["uri"] == "news://sources/health"
    assert payload["success"] is True
    assert payload["data"]["source_count"] == 1


def test_news_cli_mcp_get_prompt_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "MCPApplicationService", _FakeMCPService)

    exit_code = news_cli.main(
        [
            "mcp",
            "get-prompt",
            "news.evidence_audit",
            "--args-json",
            "{\"run_id\": \"run-1\"}",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["name"] == "news.evidence_audit"
    assert payload["success"] is True
    assert "run-1" in payload["messages"][0]["content"]


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

    def capability_manifest(self):
        return _FakeResult(
            {
                "version": "1.0",
                "server_name": "NewsRoom",
                "transport": "stdio/http",
                "auth_required": True,
                "default_permission": "mcp:read",
                "schema_version": "newsroom.mcp_capability_manifest.v1",
                "boundary": "inbound_mcp_server",
                "capability_count": 1,
                "capabilities": [
                    {
                        "name": "news.source.health",
                        "kind": "tool",
                        "title": "Read source health",
                        "description": "Read source health.",
                        "permission": "sources:read",
                        "read_only": True,
                        "category": "sources",
                        "boundary": "inbound_mcp_server",
                        "risk_level": "low",
                        "requires_approval": False,
                        "uri_template": None,
                        "input_schema": {},
                        "output_mime_type": None,
                        "metadata": {},
                    }
                ],
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

    def read_resource(self, uri):
        return _FakeResult(
            {
                "uri": uri,
                "success": True,
                "mime_type": "application/json",
                "data": {"source_count": 1},
                "error_type": None,
                "error_message": None,
            }
        )

    def get_prompt(self, name, arguments):
        return _FakeResult(
            {
                "name": name,
                "success": True,
                "description": "Prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Audit {arguments.get('run_id')}",
                    }
                ],
                "error_type": None,
                "error_message": None,
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    @property
    def success(self):
        return self.payload.get("success", True)

    def to_dict(self):
        return self.payload


class _FakeToolResult(_FakeResult):
    pass
