from __future__ import annotations

from framework.artifacts import ArtifactManager, ArtifactReference
from framework.workflow.checkpoint import CheckpointReference


def test_artifact_reference_new_and_legacy_payload_round_trip() -> None:
    ref = ArtifactReference.from_dict(
        {
            "artifact_id": "a1",
            "run_id": "run-1",
            "kind": "metrics",
            "path": "metrics.json",
            "content_type": "application/json",
            "checksum": "abc",
            "size_bytes": 12,
            "metadata": {"source": "test"},
        }
    )
    legacy = ArtifactReference.from_dict({"artifact_id": "a2", "uri": "old.txt"})

    assert ref.uri == "metrics.json"
    assert ref.to_dict()["path"] == "metrics.json"
    assert ref.to_dict()["run_id"] == "run-1"
    assert legacy.uri == "old.txt"


def test_checkpoint_reference_round_trip() -> None:
    ref = CheckpointReference(
        checkpoint_id="cp-1",
        run_id="run-1",
        step_id="s1",
        status="created",
        path="checkpoints/cp-1.json",
        metadata={"event_offset": 3},
    )

    restored = CheckpointReference.from_dict(ref.to_dict())

    assert restored.checkpoint_id == "cp-1"
    assert restored.metadata["event_offset"] == 3


def test_artifact_manager_run_manifest_helpers(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")

    manifest = manager.create_run_manifest(
        run_id="run-1",
        workflow_id="wf",
        workflow_version="1.0",
        started_at="2026-05-21T00:00:00Z",
    )
    manifest = manager.append_manifest_artifact(
        "run-1",
        artifact_key="metrics",
        relative_path="metrics.json",
        artifact_ref=ArtifactReference(
            artifact_id="metrics",
            run_id="run-1",
            kind="metrics",
            uri="metrics.json",
            content_type="application/json",
            size_bytes=2,
        ),
    )
    finalized = manager.finalize_run_manifest("run-1", {"status": "succeeded"})
    restored = manager.read_run_manifest("run-1")

    assert manifest["artifacts"]["metrics"] == "metrics.json"
    assert manifest["artifact_refs"][0]["artifact_id"] == "metrics"
    assert manifest["artifact_index"][0]["path"] == "metrics.json"
    assert finalized["status"] == "succeeded"
    assert restored["run_type"] == "workflow"
