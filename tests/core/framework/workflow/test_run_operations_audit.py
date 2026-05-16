from __future__ import annotations

import json

from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    WorkflowOperationStatus,
)


def test_cancel_run_writes_requested_and_applied_audit_events(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="running")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.cancel_run(
        "run-1",
        "manual cancel",
        actor=OperationActor(actor_id="devin"),
    )

    events = _events(tmp_path, "run-1")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert [event["event_type"] for event in events] == [
        "run_operation_requested",
        "run_operation_applied",
    ]
    assert events[0]["payload"]["operation_type"] == "cancel_run"


def test_rejected_operation_writes_rejected_event(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="cancelled")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.cancel_run("run-1", "again")

    assert result.status == WorkflowOperationStatus.REJECTED
    assert _events(tmp_path, "run-1")[-1]["event_type"] == "run_operation_rejected"


def test_manifest_operations_record_and_count(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="running")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.cancel_run(
        "run-1",
        "manual cancel",
        actor=OperationActor(actor_id="devin"),
    )

    manifest = _manifest(tmp_path, "run-1")
    assert manifest["operation_count"] == 1
    assert manifest["operations"][0]["operation_id"] == result.operation_id
    assert manifest["operations"][0]["operation_type"] == "cancel_run"
    assert manifest["operations"][0]["status"] == "applied"
    assert manifest["operations"][0]["actor_id"] == "devin"
    assert manifest["operations"][0]["reason"] == "manual cancel"


def _write_run_manifest(tmp_path, run_id: str, *, status: str) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": "daily",
                "workflow_version": "1.0",
                "profile": "test",
                "status": status,
                "operations": [],
            }
        ),
        encoding="utf-8",
    )


def _events(tmp_path, run_id: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (tmp_path / run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def _manifest(tmp_path, run_id: str) -> dict:
    return json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
