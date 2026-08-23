from __future__ import annotations

from hashlib import sha256

import pytest

from infrastructure.storage.indexing import (
    GraphArtifactBindingEvidenceSource,
    GraphArtifactBindingKind,
    GraphArtifactBindingProjection,
)


_EVIDENCE = "sha256:" + "a" * 64


def test_node_binding_round_trips_with_typed_node_instance() -> None:
    binding = GraphArtifactBindingProjection.for_node(
        artifact_id="analysis",
        node_id="analyze",
        node_instance_id="analyze:1",
        attempt_id="attempt-1",
        evidence_ref=_EVIDENCE,
        evidence_source=GraphArtifactBindingEvidenceSource.WORKER_SIDE_EFFECT_INTENT,
    )

    assert binding.kind is GraphArtifactBindingKind.NODE
    assert binding.node_instance_id == "analyze:1"
    assert GraphArtifactBindingProjection.from_dict(binding.to_dict()) == binding
    writer_binding = binding.to_node_binding()
    assert writer_binding.node_instance_id == "analyze:1"
    assert writer_binding.evidence_ref == binding.evidence_ref


def test_system_binding_has_no_node_identity_even_when_terminal_labels_exist() -> None:
    binding = GraphArtifactBindingProjection.for_system(
        artifact_id="harness-trace",
        evidence_ref="sha256:" + sha256(b"terminal-authority").hexdigest(),
        evidence_source=GraphArtifactBindingEvidenceSource.CONTROLLER_TERMINAL_AUTHORITY,
    )

    assert binding.kind is GraphArtifactBindingKind.SYSTEM
    assert binding.node_id is None
    assert binding.node_instance_id is None
    assert binding.attempt_id is None
    with pytest.raises(ValueError, match="no node writer input"):
        binding.to_node_binding()


@pytest.mark.parametrize(
    "mutator",
    (
        lambda payload: payload.update(node_instance_id=None),
        lambda payload: payload.update(kind="system"),
        lambda payload: payload.update(binding_ref=_EVIDENCE),
    ),
)
def test_node_binding_rejects_missing_or_tampered_identity(mutator) -> None:
    binding = GraphArtifactBindingProjection.for_node(
        artifact_id="analysis",
        node_id="analyze",
        node_instance_id="analyze:1",
        attempt_id="attempt-1",
        evidence_ref=_EVIDENCE,
        evidence_source=GraphArtifactBindingEvidenceSource.WORKER_SIDE_EFFECT_INTENT,
    )
    payload = binding.to_dict()
    mutator(payload)

    with pytest.raises(ValueError):
        GraphArtifactBindingProjection.from_dict(payload)
