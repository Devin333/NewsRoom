from __future__ import annotations

import pytest

from framework.agent.artifacts import ArtifactManager, ArtifactReference
from framework.workflow.checkpoint import CheckpointReference
from framework.workflow.runtime.manifest import RunManifestError


def test_artifact_manifest_contract_helpers_and_refs(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-artifact-contract")
    manager.create_run_manifest(
        run_id="run-artifact-contract",
        workflow_id="wf",
        workflow_version="1.0",
        started_at="2026-05-21T00:00:00Z",
    )

    manifest = manager.append_manifest_artifact(
        "run-artifact-contract",
        artifact_key="metrics",
        relative_path="metrics.json",
        artifact_ref=ArtifactReference(
            artifact_id="metrics",
            run_id="run-artifact-contract",
            kind="metrics",
            uri="metrics.json",
            content_type="application/json",
            size_bytes=2,
        ),
    )
    checkpoint = CheckpointReference(
        checkpoint_id="cp-1",
        run_id="run-artifact-contract",
        step_id="s1",
        status="created",
        path="checkpoints/cp-1.json",
    )

    assert manifest["artifacts"]["metrics"] == "metrics.json"
    assert manifest["artifact_refs"][0]["artifact_id"] == "metrics"
    assert manifest["artifact_index"][0]["path"] == "metrics.json"
    assert CheckpointReference.from_dict(checkpoint.to_dict()).path == "checkpoints/cp-1.json"

    with pytest.raises(RunManifestError):
        manager.append_manifest_artifact(
            "run-artifact-contract",
            artifact_key="bad",
            relative_path="../bad.json",
        )
