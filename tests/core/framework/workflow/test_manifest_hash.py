from core.framework.specs import WorkflowStatus
from core.framework.workflow import (
    LocalArtifactPublisher,
    WorkflowRunManifest,
    manifest_hash,
)


def test_manifest_hash_is_stable_for_same_content(tmp_path) -> None:
    manifest_a = _manifest()
    manifest_b = _manifest()

    assert manifest_hash(manifest_a) == manifest_hash(manifest_b)


def test_manifest_hash_changes_when_artifact_changes(tmp_path) -> None:
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
    manifest = _manifest()
    before = manifest_hash(manifest)

    manifest.add_artifact(publish.artifact_ref)

    assert manifest_hash(manifest) != before


def test_manifest_hash_changes_when_operation_changes() -> None:
    manifest = _manifest()
    before = manifest_hash(manifest)

    manifest.add_operation({"operation": "skip_step", "step_id": "draft"})

    assert manifest_hash(manifest) != before


def test_manifest_hash_ignores_manifest_hash_field() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["manifest_hash"] = "different"

    assert manifest_hash(payload) == manifest_hash(manifest)


def _manifest() -> WorkflowRunManifest:
    return WorkflowRunManifest(
        run_id="run-1",
        workflow_id="wf",
        workflow_version="1.0",
        status=WorkflowStatus.SUCCEEDED,
        created_at="2026-05-16T00:00:00Z",
        updated_at="2026-05-16T00:00:00Z",
        runner_versions={"write": "1.0.0"},
    )
