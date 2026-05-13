from __future__ import annotations

from typing import Any

from core.framework.specs import WorkflowSpec, WorkflowStatus


RUN_MANIFEST_SCHEMA_VERSION = "newsroom.workflow_run_manifest.v1"

REQUIRED_RUN_ARTIFACTS: dict[str, str] = {
    "request": "request.json",
    "workflow_spec": "workflow_spec.json",
    "workflow_version": "workflow_version.json",
    "events": "events.jsonl",
    "manifest": "manifest.json",
    "data_buffer_snapshot": "data_buffer_snapshot.json",
    "data_buffer_initial": "data_buffer.initial.json",
    "data_buffer_final": "data_buffer.final.json",
    "data_buffer_diff": "data_buffer.diff.json",
    "step_results": "step_results.json",
    "metrics": "metrics.json",
    "redaction_report": "redaction_report.json",
}


def build_run_manifest(
    *,
    run_id: str,
    workflow: WorkflowSpec,
    profile: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow.version,
        "profile": profile,
        "status": WorkflowStatus.RUNNING.value,
        "started_at": started_at,
        "finished_at": None,
        "path": [],
        "steps": {},
        "artifacts": dict(REQUIRED_RUN_ARTIFACTS),
    }


def manifest_schema_version(manifest: dict[str, Any]) -> str | None:
    value = manifest.get("schema_version")
    if value is None:
        return None
    return str(value)
