from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.agent.artifacts import ArtifactStoreMetadataError
from framework.events.canonical import checksum_for
from framework.harness.artifacts import GraphTerminalArtifact, GraphTerminalManifest
from infrastructure.storage.artifacts import FilesystemGraphTerminalArtifactStore


_STARTED_AT = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def test_graph_terminal_store_owns_staging_and_terminal_manifest_contract(
    tmp_path,
) -> None:
    store = FilesystemGraphTerminalArtifactStore(tmp_path)
    artifact = _artifact()

    staged = store.stage_artifact(run_id="run-artifact-contract", artifact=artifact)
    committed = store.write_terminal_manifest(_manifest(artifact))

    assert staged == artifact
    assert store.list_staged_artifacts("run-artifact-contract") == (artifact,)
    assert committed.artifact("metrics") == artifact
    assert store.read_terminal_manifest("run-artifact-contract") == committed
    assert store.stage_artifact(
        run_id="run-artifact-contract",
        artifact=artifact,
    ) == artifact


def test_graph_terminal_manifest_is_immutable_except_compare_and_swap(
    tmp_path,
) -> None:
    store = FilesystemGraphTerminalArtifactStore(tmp_path)
    artifact = _artifact()
    committed = store.write_terminal_manifest(_manifest(artifact))
    updated = committed.without_artifact("metrics")

    with pytest.raises(ArtifactStoreMetadataError, match="different content"):
        store.write_terminal_manifest(updated)
    with pytest.raises(ArtifactStoreMetadataError, match="changed before replacement"):
        store.replace_terminal_manifest(
            updated,
            expected_manifest_hash="sha256:" + "f" * 64,
        )

    replaced = store.replace_terminal_manifest(
        updated,
        expected_manifest_hash=committed.manifest_hash or "",
    )
    assert replaced.artifacts == ()
    assert replaced.manifest_hash != committed.manifest_hash


def test_terminal_commit_rejects_new_staging_members(tmp_path) -> None:
    store = FilesystemGraphTerminalArtifactStore(tmp_path)
    store.write_terminal_manifest(_manifest(_artifact()))

    with pytest.raises(ArtifactStoreMetadataError, match="already committed"):
        store.stage_artifact(
            run_id="run-artifact-contract",
            artifact=replace(_artifact(), artifact_key="late", artifact_id="late"),
        )


def _artifact() -> GraphTerminalArtifact:
    return GraphTerminalArtifact(
        artifact_key="metrics",
        artifact_id="metrics",
        ref="artifact://run-artifact-contract/metrics",
        relative_path="artifacts/metrics.json",
        content_checksum="sha256:" + "1" * 64,
        byte_size=2,
        media_type="application/json",
        node_id="publish",
        attempt_id="attempt-1",
        required_for_replay=True,
        required_for_publication=True,
    )


def _manifest(artifact: GraphTerminalArtifact) -> GraphTerminalManifest:
    return GraphTerminalManifest(
        tenant_id="tenant-1",
        run_id="run-artifact-contract",
        graph_id="research.artifact-contract",
        graph_version="1.0.0",
        graph_schema_version="1.0.0",
        compiler_version="1.0.0",
        normalized_graph_checksum=checksum_for({"graph": "artifact-contract"}),
        status="succeeded",
        started_at=_STARTED_AT,
        completed_at=_STARTED_AT + timedelta(seconds=1),
        terminal_state_ref=checksum_for({"state": "terminal"}),
        checkpoint_ref="graph-state://run-artifact-contract/terminal",
        terminal_node_ids=("publish",),
        gate_evidence_refs=(checksum_for({"gate": "accepted"}),),
        artifacts=(artifact,),
    )
