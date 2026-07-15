from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from framework.workflow.operations import (
    OperationResult,
    WorkflowOperationStatus,
    WorkflowOperationType,
)
from interfaces.api import create_app
from interfaces.services.run_operation_service import RunOperationApplicationService
from infrastructure.storage.events.sqlite import SQLiteEventStore


_OPERATION_REQUESTS = (
    ("cancel", {"reason": "stop"}),
    ("rerun-from-step", {"step_id": "collect"}),
    ("resume-with-patch", {"patch": {"decision": "approve"}}),
    ("skip-step", {"step_id": "optional", "reason": "not needed"}),
    (
        "mark-blocked-resolved",
        {
            "reason": "fixed",
            "resolved_by": "operator",
            "resolution_type": "manual",
        },
    ),
)


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
    manifest = json.loads((tmp_path / "run-1" / "manifest.json").read_text())

    assert response.status_code == 200
    assert payload["data"]["status"] in {"accepted", "rejected", "applied", "failed"}
    assert payload["data"]["operation_type"] == "cancel_run"
    assert [event["event_type"] for event in events] == [
        "run_operation_requested",
        "run_operation_applied",
    ]
    assert all(
        event["projection_schema"] == "newsroom.workflow-event-projection/v1"
        for event in events
    )
    assert manifest["event_projection_high_watermark"] == 2
    assert manifest["event_projection_checksum"].startswith("sha256:")
    assert (tmp_path / "_records" / "events.sqlite3").is_file()


def test_operation_missing_run_returns_run_not_found(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.post("/api/v1/runs/missing/operations/cancel", json={"reason": "stop"})
    payload = response.json()

    assert response.status_code == 404
    assert payload["error"]["code"] == "run_not_found"


def test_operation_unsafe_run_id_returns_400_before_service_side_effect(tmp_path) -> None:
    client = TestClient(_app(tmp_path))

    response = client.post(
        "/api/v1/runs/run:stream/operations/cancel",
        json={"reason": "stop"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_run_operation_request"
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("operation_path", "body"),
    _OPERATION_REQUESTS,
)
def test_operation_refuses_to_overwrite_unmigrated_legacy_events(
    tmp_path,
    operation_path: str,
    body: dict[str, Any],
) -> None:
    legacy_event = {
        "schema_version": "newsroom.event_record.v1",
        "event_id": "legacy-event-1",
        "run_id": "run-legacy",
        "event_type": "workflow_started",
        "occurred_at": "2026-07-15T00:00:00Z",
        "payload": {"workflow_version": "1.0", "profile": "legacy"},
    }
    legacy_bytes = (json.dumps(legacy_event, sort_keys=True) + "\n").encode("utf-8")
    _write_manifest(
        tmp_path,
        "run-legacy",
        status="running",
        events_content=legacy_bytes.decode("utf-8"),
    )
    manifest_path = tmp_path / "run-legacy" / "manifest.json"
    events_path = tmp_path / "run-legacy" / "events.jsonl"
    original_manifest = manifest_path.read_bytes()
    original_events = events_path.read_bytes()
    client = TestClient(_app(tmp_path))

    response = client.post(
        f"/api/v1/runs/run-legacy/operations/{operation_path}",
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_run_operation_request"
    assert "migrated" in response.json()["error"]["message"]
    assert events_path.read_bytes() == original_events
    assert manifest_path.read_bytes() == original_manifest
    assert not (tmp_path / "run-legacy" / "cancel.json").exists()
    event_store = SQLiteEventStore(tmp_path / "_records" / "events.sqlite3")
    assert event_store.get_stream_high_watermark("run:run-legacy") is None


@pytest.mark.parametrize(
    ("operation_path", "body"),
    _OPERATION_REQUESTS,
)
@pytest.mark.parametrize("events_artifact", ["empty", "missing"])
def test_operation_refuses_declared_projection_with_missing_history(
    tmp_path,
    operation_path: str,
    body: dict[str, Any],
    events_artifact: str,
) -> None:
    run_id = "run-declared-history"
    _write_manifest(tmp_path, run_id, status="running")
    run_dir = tmp_path / run_id
    manifest_path = run_dir / "manifest.json"
    events_path = run_dir / "events.jsonl"
    checksum = f"sha256:{'0' * 64}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "event_projection": {
                "path": "events.jsonl",
                "stream_id": f"run:{run_id}",
                "high_watermark": 1,
                "event_count": 1,
                "checksum": checksum,
            },
            "event_projection_high_watermark": 1,
            "event_projection_checksum": checksum,
            "event_count": 1,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    if events_artifact == "missing":
        events_path.unlink()
    original_run_files = _snapshot_files(run_dir)
    client = TestClient(_app(tmp_path))

    response = client.post(
        f"/api/v1/runs/{run_id}/operations/{operation_path}",
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_run_operation_request"
    assert "migrated" in response.json()["error"]["message"]
    assert _snapshot_files(run_dir) == original_run_files
    event_store = SQLiteEventStore(tmp_path / "_records" / "events.sqlite3")
    assert event_store.get_stream_high_watermark(f"run:{run_id}") is None


@pytest.mark.parametrize(("operation_path", "body"), _OPERATION_REQUESTS)
def test_operation_refuses_manifest_run_id_mismatch(
    tmp_path,
    operation_path: str,
    body: dict[str, Any],
) -> None:
    requested_run_id = "run-requested"
    manifest_run_id = "run-other"
    _write_manifest(tmp_path, requested_run_id, status="running")
    _write_manifest(tmp_path, manifest_run_id, status="running")
    requested_manifest_path = tmp_path / requested_run_id / "manifest.json"
    requested_manifest = json.loads(requested_manifest_path.read_text(encoding="utf-8"))
    requested_manifest["run_id"] = manifest_run_id
    requested_manifest_path.write_text(json.dumps(requested_manifest), encoding="utf-8")
    original_requested_files = _snapshot_files(tmp_path / requested_run_id)
    original_other_files = _snapshot_files(tmp_path / manifest_run_id)
    client = TestClient(_app(tmp_path))

    response = client.post(
        f"/api/v1/runs/{requested_run_id}/operations/{operation_path}",
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_run_operation_request"
    assert "run_id" in response.json()["error"]["message"]
    assert _snapshot_files(tmp_path / requested_run_id) == original_requested_files
    assert _snapshot_files(tmp_path / manifest_run_id) == original_other_files
    event_store = SQLiteEventStore(tmp_path / "_records" / "events.sqlite3")
    assert event_store.get_stream_high_watermark(f"run:{requested_run_id}") is None
    assert event_store.get_stream_high_watermark(f"run:{manifest_run_id}") is None


@pytest.mark.parametrize(("operation_path", "body"), _OPERATION_REQUESTS)
@pytest.mark.parametrize(
    "missing_watermark_key",
    ["event_projection.high_watermark", "event_projection_high_watermark"],
)
def test_operation_refuses_incomplete_empty_projection_metadata(
    tmp_path,
    operation_path: str,
    body: dict[str, Any],
    missing_watermark_key: str,
) -> None:
    run_id = "run-incomplete-projection"
    _write_manifest(tmp_path, run_id, status="running")
    run_dir = tmp_path / run_id
    manifest_path = run_dir / "manifest.json"
    empty_checksum = (
        "sha256:e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "event_projection": {
                "path": "events.jsonl",
                "stream_id": f"run:{run_id}",
                "high_watermark": None,
                "event_count": 0,
                "checksum": empty_checksum,
            },
            "event_projection_high_watermark": None,
            "event_projection_checksum": empty_checksum,
            "event_count": 0,
        }
    )
    if missing_watermark_key == "event_projection.high_watermark":
        manifest["event_projection"].pop("high_watermark")
    else:
        manifest.pop("event_projection_high_watermark")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original_run_files = _snapshot_files(run_dir)
    client = TestClient(_app(tmp_path))

    response = client.post(
        f"/api/v1/runs/{run_id}/operations/{operation_path}",
        json=body,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_run_operation_request"
    assert "metadata" in response.json()["error"]["message"]
    assert _snapshot_files(run_dir) == original_run_files
    event_store = SQLiteEventStore(tmp_path / "_records" / "events.sqlite3")
    assert event_store.get_stream_high_watermark(f"run:{run_id}") is None


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
        run_operation_service_factory=lambda: RunOperationApplicationService(
            root,
            event_env={},
        ),
        audit_emitter_factory=None,
    )


def _write_manifest(root, run_id, *, status, events_content: str = "") -> None:
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
    (run_dir / "events.jsonl").write_text(events_content, encoding="utf-8")


def _snapshot_files(root) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


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
