import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    RUN_MANIFEST_SCHEMA_VERSION,
    RunManifestError,
    StepRunnerRegistry,
    WorkflowExecutor,
    manifest_schema_version,
    validate_run_manifest,
)


def test_terminal_manifest_artifacts_have_metadata(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.echo", lambda buffer: {"echo": buffer.read("request")["topic"]})
    spec = WorkflowSpec(
        workflow_id="manifest-contract",
        name="Manifest Contract",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                "echo",
                "sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions)),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-manifest")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.manifest["schema_version"] == RUN_MANIFEST_SCHEMA_VERSION
    assert "output" in result.manifest["artifacts"]
    assert {"events", "metrics", "redaction_report"} <= set(result.manifest["artifacts"])
    for key, path in result.manifest["artifacts"].items():
        assert not path.startswith(("/", "\\"))
        assert ".." not in path.split("/")
        metadata = result.manifest["artifact_metadata"][key]
        assert metadata["checksum"]
        assert metadata["content_type"]
        assert isinstance(metadata["size_bytes"], int)


def test_manifest_validation_rejects_missing_artifact_metadata() -> None:
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": "run-1",
        "workflow_id": "wf",
        "workflow_version": "1.0",
        "profile": "test",
        "status": "succeeded",
        "started_at": "2026-05-14T00:00:00Z",
        "finished_at": "2026-05-14T00:00:01Z",
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
        "artifact_metadata": {"output": {"checksum": "abc", "content_type": "application/json", "size_bytes": 2}},
    }

    with pytest.raises(RunManifestError, match="artifact metadata is missing"):
        validate_run_manifest(manifest, require_terminal_artifact=True)


def test_manifest_schema_version_tolerates_legacy_read() -> None:
    assert manifest_schema_version({}) is None


def test_quality_manifest_fields_only_from_quality_result(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register(
        "sample.quality",
        lambda buffer: {
            "quality_result": {"route": "publish", "decision": "approved"},
            "report_quality_summary": {"quality_score": 0.97},
        },
    )
    spec = WorkflowSpec(
        workflow_id="quality-manifest",
        name="Quality Manifest",
        version="1.0",
        start_step_id="quality",
        steps=[
            StepSpec(
                "quality",
                "sample.quality",
                write_keys=["quality_result", "report_quality_summary"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions)),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-quality-manifest")
    manifest = json.loads((tmp_path / "run-quality-manifest" / "manifest.json").read_text(encoding="utf-8"))

    assert result.status == WorkflowStatus.SUCCEEDED
    assert manifest["quality_score"] == 0.97
    assert manifest["quality_route"] == "publish"
    assert manifest["quality_decision"] == "approved"
