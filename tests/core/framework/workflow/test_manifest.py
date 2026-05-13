import pytest

from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow import (
    REQUIRED_RUN_ARTIFACTS,
    RUN_MANIFEST_SCHEMA_VERSION,
    RunManifestError,
    build_run_manifest,
    manifest_schema_version,
    manifest_step_artifact_key,
    register_manifest_artifact,
    register_manifest_step_artifact,
    validate_run_manifest,
)
from storage.artifacts import ArtifactRef


def test_build_run_manifest_sets_schema_version_and_required_artifacts() -> None:
    workflow = WorkflowSpec(
        workflow_id="manifest-sample",
        name="Manifest Sample",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["echo"],
                required_output_keys=["echo"],
            )
        ],
    )

    manifest = build_run_manifest(
        run_id="run-1",
        workflow=workflow,
        profile="test",
        started_at="2026-05-13T01:02:03Z",
    )

    assert manifest["schema_version"] == RUN_MANIFEST_SCHEMA_VERSION
    assert manifest_schema_version(manifest) == RUN_MANIFEST_SCHEMA_VERSION
    assert manifest["run_id"] == "run-1"
    assert manifest["workflow_id"] == "manifest-sample"
    assert manifest["workflow_version"] == "1.0"
    assert manifest["profile"] == "test"
    assert manifest["status"] == "running"
    assert manifest["started_at"] == "2026-05-13T01:02:03Z"
    assert manifest["finished_at"] is None
    assert manifest["path"] == []
    assert manifest["steps"] == {}
    assert manifest["artifacts"] == REQUIRED_RUN_ARTIFACTS
    assert manifest["artifacts"] is not REQUIRED_RUN_ARTIFACTS


def test_manifest_schema_version_tolerates_legacy_manifest() -> None:
    assert manifest_schema_version({}) is None


def test_register_manifest_artifact_normalizes_and_validates_paths() -> None:
    manifest = {"artifacts": {}}

    path = register_manifest_artifact(manifest, "step.output", "steps\\draft\\output.json")

    assert path == "steps/draft/output.json"
    assert manifest["artifacts"]["step.output"] == "steps/draft/output.json"
    with pytest.raises(RunManifestError, match="relative to the run directory"):
        register_manifest_artifact(manifest, "bad", "../outside.json")
    with pytest.raises(RunManifestError, match="artifact key is required"):
        register_manifest_artifact(manifest, "", "output.json")


def test_register_manifest_step_artifact_records_payload_and_artifact_key() -> None:
    manifest = {"artifacts": {}}
    artifact_ref = ArtifactRef(
        artifact_id="artifact-output",
        run_id="run-1",
        step_id="draft",
        artifact_type="step_output",
        path="steps/draft/output.json",
        content_type="application/json",
    )

    path = register_manifest_step_artifact(manifest, artifact_ref)

    assert path == "steps/draft/output.json"
    assert manifest_step_artifact_key(artifact_ref) == "step.draft.step_output.artifact-output"
    assert manifest["artifacts"]["step.draft.step_output.artifact-output"] == (
        "steps/draft/output.json"
    )
    assert manifest["step_artifacts"][0]["artifact_id"] == "artifact-output"


def test_validate_run_manifest_accepts_complete_terminal_manifest() -> None:
    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")

    validate_run_manifest(manifest, require_terminal_artifact=True)


def test_validate_run_manifest_rejects_missing_required_fields() -> None:
    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")
    del manifest["workflow_id"]

    with pytest.raises(RunManifestError, match="missing required field"):
        validate_run_manifest(manifest, require_terminal_artifact=True)


def test_validate_run_manifest_rejects_bad_schema_and_artifact_path() -> None:
    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")
    manifest["schema_version"] = "unknown"

    with pytest.raises(RunManifestError, match="unsupported run manifest schema_version"):
        validate_run_manifest(manifest)

    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")
    manifest["artifacts"]["output"] = "../outside.json"
    with pytest.raises(RunManifestError, match="relative to the run directory"):
        validate_run_manifest(manifest, require_terminal_artifact=True)


def test_validate_run_manifest_rejects_missing_terminal_artifact() -> None:
    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")
    del manifest["artifacts"]["output"]

    with pytest.raises(RunManifestError, match="requires artifact: output"):
        validate_run_manifest(manifest, require_terminal_artifact=True)


def test_validate_run_manifest_rejects_unmapped_step_artifact() -> None:
    manifest = _terminal_manifest(status="succeeded", terminal_artifact_key="output")
    artifact_ref = ArtifactRef(
        artifact_id="artifact-output",
        run_id="run-1",
        step_id="draft",
        artifact_type="step_output",
        path="steps/draft/output.json",
        content_type="application/json",
    )
    manifest["step_artifacts"] = [artifact_ref.to_dict()]

    with pytest.raises(RunManifestError, match="missing artifact map entry"):
        validate_run_manifest(manifest, require_terminal_artifact=True)


def _terminal_manifest(*, status: str, terminal_artifact_key: str) -> dict:
    manifest = build_run_manifest(
        run_id="run-1",
        workflow=WorkflowSpec(
            workflow_id="manifest-sample",
            name="Manifest Sample",
            version="1.0",
            start_step_id="echo",
            steps=[
                StepSpec(
                    step_id="echo",
                    implementation="sample.echo",
                    read_keys=["request"],
                    write_keys=["echo"],
                    required_output_keys=["echo"],
                )
            ],
        ),
        profile="test",
        started_at="2026-05-13T01:02:03Z",
    )
    manifest["status"] = status
    manifest["finished_at"] = "2026-05-13T01:02:04Z"
    register_manifest_artifact(manifest, terminal_artifact_key, f"{terminal_artifact_key}.json")
    return manifest
