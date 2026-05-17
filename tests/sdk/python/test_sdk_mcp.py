from __future__ import annotations

from newsroom_sdk import NewsRoomClient


def test_mcp_resource_paths_and_payloads() -> None:
    request_func = _Recorder()
    client = NewsRoomClient("https://news.example", request_func=request_func)

    assert client.mcp.catalog()["ok"] is True
    assert client.mcp.manifest()["ok"] is True
    assert client.mcp.call_tool("news.report.latest", {"limit": 1})["ok"] is True
    assert client.mcp.read_resource("news://reports/latest")["ok"] is True
    assert client.mcp.get_prompt("news.run.diagnose", {"run_id": "run-1"})["ok"] is True

    assert [(call["method"], call["path"]) for call in request_func.calls] == [
        ("GET", "/api/v1/mcp/catalog"),
        ("GET", "/api/v1/mcp/manifest"),
        ("POST", "/api/v1/mcp/tools/news.report.latest/call"),
        ("POST", "/api/v1/mcp/resources/read"),
        ("POST", "/api/v1/mcp/prompts/news.run.diagnose/get"),
    ]
    assert request_func.calls[2]["json"] == {"arguments": {"limit": 1}}
    assert request_func.calls[3]["json"] == {"uri": "news://reports/latest"}
    assert request_func.calls[4]["json"] == {"arguments": {"run_id": "run-1"}}


class _Recorder:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, method, path, *, headers, json=None, params=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json": json,
                "params": params,
            }
        )
        return {
            "success": True,
            "data": {"ok": True},
            "request_id": "req-1",
            "schema_version": "1.0",
        }
