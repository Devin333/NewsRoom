from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.services.approval_service import ApprovalApplicationService


def test_approval_api_lifecycle_uses_local_json_store(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))

    submit_response = client.post(
        "/api/v1/approvals",
        json={
            "requested_action": "publish_report",
            "risk_level": "high",
            "reason": "operator approval required",
            "payload": {"report_id": "report-1"},
            "requested_by": "worker",
        },
    )
    submitted = submit_response.json()
    approval_id = submitted["data"]["approval_id"]

    list_response = client.get("/api/v1/approvals?status=pending")
    approve_response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator", "reason": "ready"},
    )
    show_response = client.get(f"/api/v1/approvals/{approval_id}")

    assert submit_response.status_code == 200
    assert submitted["success"] is True
    assert list_response.json()["data"]["approval_count"] == 1
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["approval"]["status"] == "approved"
    assert show_response.json()["data"]["approval"]["status"] == "approved"


def test_approval_api_missing_uses_unified_error(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))

    response = client.get("/api/v1/approvals/missing")
    payload = response.json()

    assert response.status_code == 404
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_not_found"


def test_approval_api_already_decided_uses_conflict(tmp_path) -> None:
    service = ApprovalApplicationService(store_path=tmp_path / "approvals.json")
    client = TestClient(create_app(approval_service_factory=lambda: service))
    approval_id = client.post(
        "/api/v1/approvals",
        json={"requested_action": "send_notification", "payload": {"channel": "email"}},
    ).json()["data"]["approval_id"]
    client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"decided_by": "operator", "reason": "not ready"},
    )

    response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decided_by": "operator"},
    )
    payload = response.json()

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["error"]["code"] == "approval_already_decided"
