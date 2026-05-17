from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from core.framework.workflow.operations import (
    OperationResult,
    WorkflowOperationStatus,
    WorkflowOperationType,
)
from interfaces.api import create_app
from interfaces.services.run_operation_service import RunOperationApplicationService


def test_cancel_operation_returns_operation_status_and_writes_event(tmp_path) -> None:
    _write_manifest(tmp_path, "run-1", status="running")
    client = TestClient(_app(tmp_path))

    response = client.post(
        "/api/v1/runs/run-1/operations/cancel",
        json={"reason": "manual stop", "actor_id": "operator"},
    )
    payload = response.json()
    events = [
        json.loads(line)
        for line in (tmp_path / "run-1" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert response.status_code == 200
    assert payload["data"]["status"] in {"accepted", "rejected", "applied", "failed"}
    assert payload["data"]["operation_type"] == "cancel_run"
    assert "run_operation_applied" in [event["event_type"] for event in events]


def test_operation_missing_run_returns_run_not_found(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.post("/api/v1/runs/missing/operations/cancel", json={"reason": "stop"})
    payload = response.json()

    assert response.status_code == 404
    assert payload["error"]["code"] == "run_not_found"


def test_operation_endpoints_delegate_to_application_service() -> None:
    fake_service = _FakeRunOperationService()
    client = TestClient(create_app(run_operation_service_factory=lambda: fake_service))

    client.post(
        "/api/v1/runs/run-1/operations/rerun-from-step",
        json={"step_id": "write", "actor_id": "operator"},
    )
    client.post(
        "/api/v1/runs/run-1/operations/resume-with-patch",
        json={"patch": {"decision": "approve"}, "actor_id": "operator"},
    )
    client.post(
        "/api/v1/runs/run-1/operations/skip-step",
        json={"step_id": "optional", "reason": "not needed", "actor_id": "operator"},
    )
    client.post(
        "/api/v1/runs/run-1/operations/mark-blocked-resolved",
        json={
            "reason": "fixed",
            "resolved_by": "operator",
            "resolution_type": "manual",
            "actor_id": "operator",
        },
    )

    assert fake_service.calls == [
        ("rerun_from_step", {"run_id": "run-1", "step_id": "write", "actor_id": "operator"}),
        (
            "resume_with_patch",
            {"run_id": "run-1", "patch": {"decision": "approve"}, "actor_id": "operator"},
        ),
        (
            "skip_step",
            {
                "run_id": "run-1",
                "step_id": "optional",
                "reason": "not needed",
                "actor_id": "operator",
            },
        ),
        (
            "mark_blocked_resolved",
            {
                "run_id": "run-1",
                "reason": "fixed",
                "resolved_by": "operator",
                "resolution_type": "manual",
                "actor_id": "operator",
            },
        ),
    ]


def _app(root):
    return create_app(
        run_operation_service_factory=lambda: RunOperationApplicationService(root),
        audit_emitter_factory=None,
    )


def _write_manifest(root, run_id, *, status) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "workflow_id": "daily",
        "workflow_version": "1.0",
        "profile": "test",
        "status": status,
        "operations": [],
        "operation_count": 0,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text("", encoding="utf-8")


@dataclass
class _FakeResult:
    operation_type: WorkflowOperationType
    run_id: str

    def to_dict(self) -> dict[str, Any]:
        return OperationResult(
            operation_id="op-test",
            operation_type=self.operation_type,
            status=WorkflowOperationStatus.ACCEPTED,
            run_id=self.run_id,
            message="accepted",
        ).to_dict()


class _FakeRunOperationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def rerun_from_step(self, run_id, *, step_id, actor_id=None, metadata=None):
        self.calls.append(
            ("rerun_from_step", {"run_id": run_id, "step_id": step_id, "actor_id": actor_id})
        )
        return _FakeResult(WorkflowOperationType.RERUN_FROM_STEP, run_id)

    def resume_with_patch(self, run_id, *, patch, actor_id=None, metadata=None):
        self.calls.append(
            ("resume_with_patch", {"run_id": run_id, "patch": patch, "actor_id": actor_id})
        )
        return _FakeResult(WorkflowOperationType.RESUME_WITH_PATCH, run_id)

    def skip_step(self, run_id, *, step_id, reason=None, actor_id=None, metadata=None):
        self.calls.append(
            (
                "skip_step",
                {"run_id": run_id, "step_id": step_id, "reason": reason, "actor_id": actor_id},
            )
        )
        return _FakeResult(WorkflowOperationType.SKIP_STEP, run_id)

    def mark_blocked_resolved(
        self,
        run_id,
        *,
        reason=None,
        resolved_by=None,
        resolution_type="manual",
        actor_id=None,
        metadata=None,
    ):
        self.calls.append(
            (
                "mark_blocked_resolved",
                {
                    "run_id": run_id,
                    "reason": reason,
                    "resolved_by": resolved_by,
                    "resolution_type": resolution_type,
                    "actor_id": actor_id,
                },
            )
        )
        return _FakeResult(WorkflowOperationType.MARK_BLOCKED_RESOLVED, run_id)
