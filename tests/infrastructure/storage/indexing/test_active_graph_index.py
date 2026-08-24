from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.artifacts import GraphTerminalArtifact
from framework.events.runtime.models import EventPage, StreamSequenceCursor
from infrastructure.storage.indexing import (
    GraphArtifactBindingEvidenceSource,
    GraphArtifactBindingKind,
    GraphArtifactBindingProjection,
    GraphStorageIndexCandidateBuilder,
    GraphStorageIndexCandidateMaterializer,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    LocalGraphStorageIndexStore,
)
from tests.infrastructure.storage.indexing.test_inactive_graph_index import (
    _SHA_A,
    _SHA_B,
    _SHA_C,
    _event,
    _events,
    _identity,
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


def test_active_builder_excludes_internal_ref_only_artifacts_from_publication_index() -> None:
    manifest = _mixed_manifest()
    internal_artifact = GraphTerminalArtifact(
        artifact_key="graph-result-" + "d" * 64,
        artifact_id="graph-result-" + "d" * 64,
        ref=f"artifact://{manifest.run_id}/graph-result-" + "d" * 64,
        relative_path="internal/graph-result.json",
        content_checksum=_SHA_A,
        byte_size=1,
        media_type="application/json",
        node_id="publish_artifacts",
        attempt_id="internal-1",
        required_for_replay=True,
        required_for_publication=True,
        metadata={
            "graph_result_ref_only": True,
            "identity_checksum": _SHA_A,
        },
    )
    manifest = _manifest_with_artifacts(
        (*manifest.artifacts, internal_artifact),
    )

    request = GraphStorageIndexCandidateBuilder.from_manifest(
        manifest=manifest,
        events=_events(manifest),
    )
    candidate = GraphStorageIndexCandidateBuilder().build(request)

    assert tuple(record.artifact_id for record in candidate.artifact_records) == (
        manifest.artifacts[0].artifact_id,
        manifest.artifacts[2].artifact_id,
    )


def test_active_builder_persists_exact_activity_identity_in_event_records() -> None:
    manifest = _manifest_with_node_binding()
    events = (
        _event(1, _identity(manifest)),
        _event(2, _identity(manifest), with_activity=True),
    )
    request = GraphStorageIndexCandidateBuilder.from_manifest(
        manifest=manifest,
        events=events,
    )

    candidate = GraphStorageIndexCandidateBuilder().build(request)
    record = candidate.event_records[1]

    assert record.node_instance_id == "analyze:1"
    assert record.activity_id == "activity-analyze-1"
    assert record.attempt == 1
    assert type(record).from_dict(record.to_dict()) == record


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


def test_materializer_reads_one_pinned_durable_prefix_before_building(tmp_path) -> None:
    manifest = _manifest_with_node_binding()
    events = _events(manifest)
    reader = _Reader(events)

    candidate = GraphStorageIndexCandidateMaterializer(
        event_reader=reader,
        page_size=1,
    ).materialize(manifest)

    assert candidate.event_high_watermark == 2
    assert tuple(request.through_sequence for request in reader.requests) == (2, 2)
    assert all(request.stream_id == f"run:{manifest.run_id}" for request in reader.requests)
    assert all(request.tenant_id == manifest.tenant_id for request in reader.requests)


def test_materializer_rejects_watermark_drift() -> None:
    manifest = _manifest_with_node_binding()
    reader = _Reader(_events(manifest), drift_after_first_read=True)

    with pytest.raises(GraphStorageIndexError) as raised:
        GraphStorageIndexCandidateMaterializer(event_reader=reader).materialize(manifest)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED


class _Reader:
    def __init__(self, events, *, drift_after_first_read: bool = False):
        self.events = tuple(events)
        self.requests = []
        self._reads = 0
        self._drift_after_first_read = drift_after_first_read

    def get_event(self, event_id, *, tenant_id=None):
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id and event.tenant_id == tenant_id
            ),
            None,
        )

    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):
        if self._drift_after_first_read and self._reads > 0:
            return 3
        return max(
            (
                event.stream_sequence
                for event in self.events
                if event.stream_id == stream_id and event.tenant_id == tenant_id
            ),
            default=None,
        )

    def read_stream(self, request):
        self._reads += 1
        self.requests.append(request)
        after = request.cursor.after_sequence if request.cursor is not None else 0
        matching = tuple(
            event
            for event in self.events
            if event.stream_id == request.stream_id
            and event.tenant_id == request.tenant_id
            and after < event.stream_sequence <= (request.through_sequence or 0)
        )[: request.limit]
        next_cursor = None
        if matching and matching[-1].stream_sequence < (request.through_sequence or 0):
            next_cursor = StreamSequenceCursor(
                stream_id=request.stream_id,
                tenant_id=request.tenant_id,
                after_sequence=matching[-1].stream_sequence,
                high_watermark=request.through_sequence,
            )
        return EventPage(
            stream_id=request.stream_id,
            tenant_id=request.tenant_id,
            events=matching,
            high_watermark=request.through_sequence,
            next_cursor=next_cursor,
        )


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
        required_for_publication=True,
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
