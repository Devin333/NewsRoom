from __future__ import annotations

from newsroom_sdk import NewsRoomClient


def test_reports_resource_paths() -> None:
    request_func = _Recorder()
    client = NewsRoomClient("https://news.example", request_func=request_func)

    assert client.reports.latest()["ok"] is True
    assert client.reports.list(limit=5)["ok"] is True
    assert client.reports.get("report/1")["ok"] is True
    assert client.reports.markdown("report/1")["ok"] is True
    assert client.reports.search("agent", limit=2)["ok"] is True

    assert [(call["method"], call["path"]) for call in request_func.calls] == [
        ("GET", "/api/v1/reports/latest"),
        ("GET", "/api/v1/reports"),
        ("GET", "/api/v1/reports/report%2F1"),
        ("GET", "/api/v1/reports/report%2F1/markdown"),
        ("GET", "/api/v1/search/reports"),
    ]
    assert request_func.calls[1]["params"] == {
        "limit": 5,
        "graph_id": None,
        "graph_ids": None,
    }
    assert request_func.calls[4]["params"] == {"q": "agent", "limit": 2}


def test_reports_resource_accepts_graph_id() -> None:
    request_func = _Recorder()
    client = NewsRoomClient("https://news.example", request_func=request_func)

    assert client.reports.list(limit=5, graph_id="research.paper_analysis")["ok"] is True

    assert request_func.calls[0]["method"] == "GET"
    assert request_func.calls[0]["path"] == "/api/v1/reports"
    assert request_func.calls[0]["params"] == {
        "limit": 5,
        "graph_id": "research.paper_analysis",
        "graph_ids": None,
    }


def test_memory_resource_search_from_sdk() -> None:
    request_func = _Recorder()
    client = NewsRoomClient("https://news.example", request_func=request_func)

    assert client.memory.search("OpenAI", collection="reports", limit=3)["ok"] is True

    assert request_func.calls[0]["method"] == "POST"
    assert request_func.calls[0]["path"] == "/api/v1/memory/search"
    assert request_func.calls[0]["json"] == {
        "query": "OpenAI",
        "collection": "reports",
        "limit": 3,
        "filters": {},
    }


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
