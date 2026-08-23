from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.artifacts import GraphTerminalArtifact
from infrastructure.storage.indexing import (
    GraphArtifactBindingEvidenceSource,
    GraphArtifactBindingKind,
    GraphArtifactBindingProjection,
    GraphStorageIndexCandidateBuilder,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    LocalGraphStorageIndexStore,
)
from tests.infrastructure.storage.indexing.test_inactive_graph_index import (
    _SHA_A,
    _SHA_B,
    _SHA_C,
    _events,
    _manifest,
)


def test_active_builder_preserves_node_and_system_bindings_through_store(
    tmp_path,
) -> None:
    manifest = _mixed_manifest()
    request = GraphStorageIndexCandidateBuilder.from_manifest(
        manifest=manifest,
        events=_events(manifest),
    )

    candidate = GraphStorageIndexCandidateBuilder().build(request)

    assert tuple(record.binding_kind for record in candidate.artifact_records) == (
        GraphArtifactBindingKind.NODE,
        GraphArtifactBindingKind.SYSTEM,
    )
    node_record, system_record = candidate.artifact_records
    assert node_record.node_instance_id == "analyze:1"
    assert node_record.binding_evidence_source is (
        GraphArtifactBindingEvidenceSource.WORKER_SIDE_EFFECT_INTENT
    )
    assert system_record.node_id is None
    assert system_record.node_instance_id is None
    assert system_record.attempt_id is None
    assert system_record.binding_evidence_source is (
        GraphArtifactBindingEvidenceSource.CONTROLLER_TERMINAL_AUTHORITY
    )

    store = LocalGraphStorageIndexStore(tmp_path / "index")
    store.write(candidate)
    restored = store.read(candidate.identity)
    assert restored.candidate == candidate


def test_active_builder_rejects_missing_explicit_binding() -> None:
    manifest = _manifest()

    with pytest.raises(GraphStorageIndexError) as raised:
        GraphStorageIndexCandidateBuilder.from_manifest(
            manifest=manifest,
            events=_events(manifest),
        )

    assert raised.value.code is GraphStorageIndexErrorCode.REQUEST_INVALID


def test_active_builder_rejects_tampered_binding_projection() -> None:
    manifest = _manifest_with_node_binding()
    artifact = manifest.artifacts[0]
    metadata = dict(artifact.metadata)
    binding = dict(metadata["graph_artifact_binding"])
    binding["node_instance_id"] = "analyze:forged"
    metadata["graph_artifact_binding"] = binding
    tampered_artifact = replace(artifact, metadata=metadata)
    tampered_manifest = _manifest_with_artifacts((tampered_artifact,))

    with pytest.raises(GraphStorageIndexError) as raised:
        GraphStorageIndexCandidateBuilder.from_manifest(
            manifest=tampered_manifest,
            events=_events(tampered_manifest),
        )

    assert raised.value.code is GraphStorageIndexErrorCode.REQUEST_INVALID


def test_active_builder_rejects_node_binding_not_proven_by_event_history() -> None:
    manifest = _manifest_with_node_binding(node_instance_id="analyze:forged")
    request = GraphStorageIndexCandidateBuilder.from_manifest(
        manifest=manifest,
        events=_events(manifest),
    )

    with pytest.raises(GraphStorageIndexError) as raised:
        GraphStorageIndexCandidateBuilder().build(request)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED


def _mixed_manifest():
    node_manifest = _manifest_with_node_binding()
    node_artifact = node_manifest.artifacts[0]
    system_projection = GraphArtifactBindingProjection.for_system(
        artifact_id="terminal-trace-1",
        evidence_ref=_SHA_B,
        evidence_source=GraphArtifactBindingEvidenceSource.CONTROLLER_TERMINAL_AUTHORITY,
    )
    system_artifact = GraphTerminalArtifact(
        artifact_key="terminal-trace",
        artifact_id="terminal-trace-1",
        ref=f"artifact://{node_manifest.run_id}/terminal-trace-1",
        relative_path="terminal/trace.json",
        content_checksum=_SHA_A,
        byte_size=1,
        media_type="application/json",
        node_id="terminal",
        attempt_id="terminal-1",
        required_for_replay=True,
        required_for_publication=False,
        metadata={"graph_artifact_binding": system_projection.to_dict()},
    )
    return _manifest_with_artifacts((node_artifact, system_artifact))


def _manifest_with_node_binding(*, node_instance_id: str = "analyze:1"):
    manifest = _manifest()
    artifact = manifest.artifacts[0]
    projection = GraphArtifactBindingProjection.for_node(
        artifact_id=artifact.artifact_id,
        node_id=artifact.node_id,
        node_instance_id=node_instance_id,
        attempt_id=artifact.attempt_id,
        evidence_ref=_SHA_C,
        evidence_source=GraphArtifactBindingEvidenceSource.WORKER_SIDE_EFFECT_INTENT,
    )
    return _manifest_with_artifacts(
        (replace(artifact, metadata={"graph_artifact_binding": projection.to_dict()}),)
    )


def _manifest_with_artifacts(artifacts):
    manifest = _manifest()
    terminal = replace(
        manifest.terminal,
        artifacts=tuple(artifacts),
        manifest_hash=None,
    )
    return type(manifest)(
        terminal=terminal,
        execution_versions=manifest.execution_versions,
    )
