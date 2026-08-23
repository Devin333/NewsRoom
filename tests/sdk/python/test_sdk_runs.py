from __future__ import annotations

from newsroom_sdk import NewsRoomClient


def test_runs_resource_paths_and_payloads() -> None:
    request_func = _Recorder()
    client = NewsRoomClient("https://news.example", request_func=request_func)

    assert client.runs.get("run/1")["ok"] is True
    assert client.runs.list(limit=10, status="running")["ok"] is True
    assert client.runs.events(
        "run/1",
        event_type="step_succeeded",
        limit=2,
        sequence_cursor="cursor-1",
    )["ok"] is True
    assert client.runs.artifacts("run/1")["ok"] is True
    assert client.runs.diagnostics("run/1")["ok"] is True
    assert client.runs.cancel("run/1", reason="manual_stop")["ok"] is True

    assert [(call["method"], call["path"]) for call in request_func.calls] == [
        ("GET", "/api/v2/graph-runs/run%2F1"),
        ("GET", "/api/v2/graph-runs"),
        ("GET", "/api/v2/graph-runs/run%2F1/events"),
        ("GET", "/api/v2/graph-runs/run%2F1/artifacts"),
        ("GET", "/api/v2/graph-runs/run%2F1/diagnostics"),
        ("POST", "/api/v2/graph-runs/run%2F1/cancel"),
    ]
    assert request_func.calls[1]["params"]["status"] == "running"
    assert request_func.calls[2]["params"]["event_type"] == "step_succeeded"
    assert request_func.calls[2]["params"]["sequence_cursor"] == "cursor-1"
    assert request_func.calls[5]["json"] == {"reason_code": "manual_stop"}


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
