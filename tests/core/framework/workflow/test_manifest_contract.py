import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    ArtifactStatus,
    FunctionStepRegistry,
    FunctionStepRunner,
    JsonManifestStore,
    LocalArtifactPublisher,
    RUN_MANIFEST_SCHEMA_VERSION,
    RunManifestError,
    StepRunnerRegistry,
    WorkflowRunManifest,
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


def test_workflow_run_manifest_records_artifacts_versions_and_operations(tmp_path) -> None:
    publisher = LocalArtifactPublisher(tmp_path)
    publish = publisher.publish_artifact(
        run_id="run-1",
        step_id="write",
        key="report_artifact",
        artifact_type="json",
        content=b"{}",
        metadata={"relative_path": "artifacts/write/report.json"},
    )
    assert publish.artifact_ref is not None

    manifest = WorkflowRunManifest(
        run_id="run-1",
        workflow_id="wf",
        workflow_version="1.0",
        status=WorkflowStatus.SUCCEEDED,
        created_at="2026-05-16T00:00:00Z",
        updated_at="2026-05-16T00:00:00Z",
        runner_versions={"write": "1.0.0"},
    )
    manifest.add_artifact(publish.artifact_ref)
    manifest.add_checkpoint("cp-1")
    manifest.add_operation({"operation": "resume_with_patch", "api_key": "secret"})
    manifest.update_metrics({"duration_ms": 12, "token": "secret"})

    assert manifest.artifacts[0].created_by_step_id == "write"
    assert manifest.runner_versions == {"write": "1.0.0"}
    assert manifest.checkpoints == ["cp-1"]
    assert manifest.operations[0]["api_key"] == "***REDACTED***"
    assert manifest.metrics["token"] == "***REDACTED***"

    store = JsonManifestStore(tmp_path)
    store.write(manifest)

    assert store.exists("run-1")
    restored = store.read("run-1")
    assert restored.run_id == "run-1"
    assert restored.artifacts[0].status == ArtifactStatus.PUBLISHED
    assert restored.runner_versions["write"] == "1.0.0"


def test_artifact_runner_adds_production_artifact_refs_to_manifest(tmp_path) -> None:
    registry = StepRunnerRegistry()
    from core.framework.workflow import ArtifactStepRunner

    registry.register(StepType.ARTIFACT, ArtifactStepRunner())
    spec = WorkflowSpec(
        workflow_id="artifact-manifest",
        name="Artifact Manifest",
        version="1.0",
        start_step_id="artifact",
        steps=[
            StepSpec(
                step_id="artifact",
                implementation="artifact.write",
                step_type=StepType.ARTIFACT,
                write_keys=["artifact_ref"],
                required_output_keys=["artifact_ref"],
                metadata={
                    "content": {"report": "ready"},
                    "relative_path": "steps/artifact/output.json",
                    "artifact_id": "artifact-output",
                    "artifact_metadata": {"token": "secret"},
                },
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-artifact-manifest")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["artifact_ref"]["content_hash"]
    assert result.output["artifact_ref"]["created_by_step_id"] == "artifact"
    manifest = json.loads((tmp_path / "run-artifact-manifest" / "manifest.json").read_text())
    assert manifest["runner_versions"]["artifact"] == "1.0.0"
    ref = next(item for item in manifest["artifact_refs"] if item["artifact_id"] == "artifact-output")
    assert ref["uri"] == "steps/artifact/output.json"
    assert ref["content_hash"]
    assert ref["created_by_step_id"] == "artifact"
    assert ref["metadata"]["token"] == "***REDACTED***"


def test_manifest_schema_version_tolerates_legacy_read() -> None:
    assert manifest_schema_version({}) is None


def test_generic_executor_does_not_publish_daily_quality_manifest_fields(tmp_path) -> None:
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
    assert "quality_score" not in manifest
    assert "quality_route" not in manifest
    assert "quality_decision" not in manifest
    assert "quality_result" not in manifest["artifacts"]
    assert "report_quality_summary" not in manifest["artifacts"]
