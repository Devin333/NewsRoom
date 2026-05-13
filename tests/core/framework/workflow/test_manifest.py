from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow import (
    REQUIRED_RUN_ARTIFACTS,
    RUN_MANIFEST_SCHEMA_VERSION,
    build_run_manifest,
    manifest_schema_version,
)


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
