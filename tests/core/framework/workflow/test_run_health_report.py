from __future__ import annotations

import hashlib
import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepStatus, WorkflowSpec
from core.framework.workflow import (
    ArtifactIntegrityInspector,
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
    WorkflowRunInspectionError,
    build_run_health_report,
    inspect_workflow_run,
)


def test_artifact_integrity_reports_missing_artifact(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {}, profile="test", run_id="health-missing")
    (tmp_path / "health-missing" / "output.json").unlink()

    inspection = inspect_workflow_run(tmp_path / "health-missing")
    report = ArtifactIntegrityInspector().inspect(
        tmp_path / "health-missing",
        inspection.manifest,
        strict=False,
    )

    assert "output" in report.missing_artifacts
    assert "output" in inspection.integrity.missing_artifact_files


def test_artifact_integrity_checksum_failure_strict_raises(tmp_path) -> None:
    run_dir = _write_checksum_run(tmp_path)
    (run_dir / "output.json").write_text('{"ok": false}', encoding="utf-8")

    with pytest.raises(WorkflowRunInspectionError, match="checksum mismatch"):
        inspect_workflow_run(run_dir, verify_checksums=True, strict=True)


def test_artifact_integrity_checksum_failure_non_strict_warns(tmp_path) -> None:
    run_dir = _write_checksum_run(tmp_path)
    (run_dir / "output.json").write_text('{"ok": false}', encoding="utf-8")

    inspection = inspect_workflow_run(run_dir, verify_checksums=True, strict=False)

    assert inspection.integrity.valid is True
    assert any("checksum mismatch" in warning for warning in inspection.integrity.warnings)


def test_health_report_exposes_layered_checks_for_missing_artifact(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {}, profile="test", run_id="health-checks")
    (tmp_path / "health-checks" / "output.json").unlink()

    health = build_run_health_report(inspect_workflow_run(tmp_path / "health-checks"))

    assert health.checks["artifact_health"] == "failed"
    assert health.checks["manifest_health"] == "failed"
    assert "rebuild" in " ".join(health.suggested_actions)


def test_health_report_marks_paused_without_checkpoint_resume_failed(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register("function", _PauseRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )
    executor.execute(_pause_spec(), {}, profile="test", run_id="health-paused-no-cp")
    manifest_path = tmp_path / "health-paused-no-cp" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["latest_checkpoint_id"] = None
    manifest["checkpoint_count"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    health = inspect_workflow_run(tmp_path / "health-paused-no-cp").health_report

    assert health.checks["resume_health"] == "failed"
    assert health.checks["checkpoint_health"] == "failed"


def test_health_report_marks_missing_events_warning(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {}, profile="test", run_id="health-no-events")
    (tmp_path / "health-no-events" / "events.jsonl").unlink()

    health = inspect_workflow_run(tmp_path / "health-no-events").health_report

    assert health.checks["event_health"] == "warning"


def _sample_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="health-sample",
        name="Health Sample",
        version="1.0",
        start_step_id="ok",
        steps=[StepSpec("ok", "sample.ok", write_keys=["ok"])],
    )


def _sample_executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("sample.ok", lambda buffer: {"ok": True})
    return WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )


def _pause_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="health-pause",
        name="Health Pause",
        version="1.0",
        start_step_id="pause",
        steps=[StepSpec("pause", "pause.now")],
    )


class _PauseRunner:
    def run(self, step, buffer):
        _ = step, buffer
        return StepOutcome(status=StepStatus.PAUSED, next_hint="pause")


def _write_checksum_run(tmp_path):
    run_dir = tmp_path / "checksum-run"
    run_dir.mkdir()
    content = '{"ok": true}'
    empty_json_checksum = hashlib.sha256(b"{}").hexdigest()
    empty_events_checksum = hashlib.sha256(b"").hexdigest()
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": "checksum-run",
        "workflow_id": "checksum",
        "workflow_version": "1.0",
        "profile": "test",
        "status": "succeeded",
        "started_at": "2026-05-16T00:00:00Z",
        "finished_at": "2026-05-16T00:00:01Z",
        "path": [],
        "steps": {},
        "artifacts": {
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
            "output": "output.json",
        },
    }
    metadata = {}
    for key in manifest["artifacts"]:
        if key == "output":
            metadata[key] = {
                "checksum": checksum,
                "content_type": "application/json",
                "size_bytes": len(content.encode("utf-8")),
            }
        elif key == "manifest":
            metadata[key] = {
                "checksum": hashlib.sha256(b"{}").hexdigest(),
                "content_type": "application/json",
                "size_bytes": 2,
            }
        elif key == "events":
            metadata[key] = {
                "checksum": empty_events_checksum,
                "content_type": "application/jsonl",
                "size_bytes": 0,
            }
        else:
            metadata[key] = {
                "checksum": empty_json_checksum,
                "content_type": "application/json",
                "size_bytes": 2,
            }
    manifest["artifact_metadata"] = metadata
    for key, path in manifest["artifacts"].items():
        if key == "manifest":
            continue
        (run_dir / path).write_text(content if key == "output" else "{}", encoding="utf-8")
    (run_dir / "events.jsonl").write_text("", encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir
