from __future__ import annotations

import json

from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    WorkflowOperationStatus,
)


def test_blocked_run_can_mark_blocked_resolved(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="blocked")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.mark_blocked_resolved(
        "run-1",
        {
            "reason": "api key rotated",
            "resolved_by": "devin",
            "resolution_type": "configuration",
            "metadata": {"ticket": "ops-1"},
        },
        actor=OperationActor(actor_id="devin"),
    )

    manifest = _manifest(tmp_path, "run-1")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert manifest["status"] == "blocked"
    assert manifest["blocked_resolution"]["operation_id"] == result.operation_id
    assert manifest["blocked_resolution"]["reason"] == "api key rotated"
    assert manifest["blocked_resolution"]["resolved_by"] == "devin"
    assert manifest["operation_count"] == 1
    assert manifest["operations"][0]["operation_type"] == "mark_blocked_resolved"


def test_succeeded_run_cannot_mark_blocked_resolved(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="succeeded")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.mark_blocked_resolved(
        "run-1",
        {
            "reason": "not blocked",
            "resolved_by": "devin",
            "resolution_type": "configuration",
            "metadata": {},
        },
    )

    assert result.status == WorkflowOperationStatus.REJECTED
    assert "blocked_resolution" not in _manifest(tmp_path, "run-1")


def test_blocked_resolution_requires_minimum_fields(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="blocked")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.mark_blocked_resolved(
        "run-1",
        {"reason": "fixed"},
    )

    assert result.status == WorkflowOperationStatus.REJECTED
    assert "resolved_by" in result.message


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


def _manifest(tmp_path, run_id: str) -> dict:
    return json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
