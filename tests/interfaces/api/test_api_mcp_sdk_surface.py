from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app


def test_api_mcp_sdk_surface_delegates_to_service() -> None:
    fake_service = _FakeMCPService()
    client = TestClient(
        create_app(
            mcp_service_factory=lambda: fake_service,
            audit_emitter_factory=None,
        )
    )

    tool_response = client.post(
        "/api/v1/mcp/tools/news.report.latest/call",
        json={"arguments": {"limit": 1}},
    )
    resource_response = client.post(
        "/api/v1/mcp/resources/read",
        json={"uri": "news://reports/latest"},
    )
    prompt_response = client.post(
        "/api/v1/mcp/prompts/news.run.diagnose/get",
        json={"arguments": {"run_id": "run-1"}},
    )

    assert tool_response.status_code == 200
    assert tool_response.json()["data"]["tool_name"] == "news.report.latest"
    assert resource_response.status_code == 200
    assert resource_response.json()["data"]["uri"] == "news://reports/latest"
    assert prompt_response.status_code == 200
    assert prompt_response.json()["data"]["name"] == "news.run.diagnose"
    assert fake_service.calls == [
        ("call_tool", "news.report.latest", {"limit": 1}),
        ("read_resource", "news://reports/latest"),
        ("get_prompt", "news.run.diagnose", {"run_id": "run-1"}),
    ]


class _FakeMCPService:
    def __init__(self) -> None:
        self.calls = []

    def catalog(self):
        return _FakeResult({"tools": [], "resources": [], "prompts": []})

    def capability_manifest(self):
        return _FakeResult({"version": "1.0", "capabilities": [], "capability_count": 0})

    def call_tool(self, tool_name, arguments):
        self.calls.append(("call_tool", tool_name, arguments))
        return _FakeResult(
            {
                "tool_name": tool_name,
                "success": True,
                "data": {"arguments": arguments},
                "error_type": None,
                "error_message": None,
            }
        )

    def read_resource(self, uri):
        self.calls.append(("read_resource", uri))
        return _FakeResult(
            {
                "uri": uri,
                "success": True,
                "mime_type": "application/json",
                "data": {"ok": True},
                "error_type": None,
                "error_message": None,
            }
        )

    def get_prompt(self, prompt_name, arguments):
        self.calls.append(("get_prompt", prompt_name, arguments))
        return _FakeResult(
            {
                "name": prompt_name,
                "success": True,
                "description": "Prompt",
                "messages": [{"role": "user", "content": "diagnose"}],
                "error_type": None,
                "error_message": None,
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)
