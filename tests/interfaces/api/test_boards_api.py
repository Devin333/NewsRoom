from __future__ import annotations

from fastapi.testclient import TestClient

from interfaces.api import create_app


def test_boards_api_registers_board_routes() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))

    response = client.get("/api/v1/boards")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert {board["board_type"] for board in payload["data"]["boards"]} >= {
        "ai_news",
        "project_radar",
        "paper_radar",
        "community_pulse",
        "cross_board",
    }
