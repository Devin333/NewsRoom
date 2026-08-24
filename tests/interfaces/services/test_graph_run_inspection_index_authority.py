from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from framework.events import default_event_schema_catalog
from framework.harness.artifacts import GraphTerminalArtifact
from infrastructure.storage.indexing import (
    GraphArtifactBindingEvidenceSource,
    GraphArtifactBindingProjection,
    GraphStorageIndexCandidateBuilder,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexReader,
    LocalGraphStorageIndexStore,
)
from interfaces.services.event_reader_service import EventAuthorizationContext, EventReaderService
from interfaces.services.run_inspection_service import GraphRunInspectionService
from tests.fixtures.graph_runs import rewrite_graph_terminal_manifest
from tests.infrastructure.storage.indexing.test_active_graph_index import (
    _Reader,
    _manifest_with_node_binding,
)
from tests.infrastructure.storage.indexing.test_inactive_graph_index import (
    _CONTENT,
    _SHA_C,
    _events,
)
from interfaces.services.run_inspection_factory import GraphRunInspectionEventAuthorizer
from interfaces.services.run_inspection_factory import build_graph_run_inspection_service
from infrastructure.storage.events import SQLiteEventStore


def _service(root, manifest, events, store) -> GraphRunInspectionService:
    authorization = EventAuthorizationContext(
        principal_id="inspection-test",
        tenant_id=manifest.tenant_id,
        authentication_evidence_ref="authn://inspection-test",
    )
    return GraphRunInspectionService(
        root,
        event_reader_service=EventReaderService(
            _Reader(events),
            authorizer=GraphRunInspectionEventAuthorizer(authorization),
        ),
        event_authorization=authorization,
        event_schema_catalog=default_event_schema_catalog(),
        graph_index_reader=GraphStorageIndexReader(store),
    )


def _write_indexed_run(tmp_path, *, manifest=None):
    manifest = manifest or _manifest_with_node_binding()
    events = _events(manifest)
    run_dir = tmp_path / manifest.run_id
    for artifact in manifest.artifacts:
        path = run_dir / artifact.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_CONTENT)
    rewrite_graph_terminal_manifest(run_dir / "manifest.json", manifest)
    request = GraphStorageIndexCandidateBuilder.from_manifest(
        manifest=manifest,
        events=events,
    )
    candidate = GraphStorageIndexCandidateBuilder().build(request)
    store = LocalGraphStorageIndexStore(tmp_path / "graph-index")
    store.write(candidate)
    return manifest, events, candidate, store


def test_inspection_steps_and_replay_use_graph_index_read_back(tmp_path) -> None:
    manifest, events, _, store = _write_indexed_run(tmp_path)
    service = _service(tmp_path, manifest, events, store)

    steps = service.get_run_steps(manifest.run_id)
    replay = service.replay_run(manifest.run_id)

    assert [step["node_instance_id"] for step in steps.steps] == ["analyze:1"]
    assert replay.events and replay.events[-1]["stream_sequence"] == 2
    assert [artifact["artifact_key"] for artifact in replay.artifacts] == ["analysis"]


def test_replay_fails_closed_when_index_artifact_diverges_from_manifest(tmp_path) -> None:
    manifest, events, candidate, _ = _write_indexed_run(tmp_path)
    forged_record = replace(
        candidate.artifact_records[0],
        relative_path="nodes/analyze/forged.json",
    )
    forged_candidate = replace(
        candidate,
        artifact_records=(forged_record,),
    )
    forged_store = LocalGraphStorageIndexStore(tmp_path / "forged-index")
    forged_store.write(forged_candidate)
    service = _service(tmp_path, manifest, events, forged_store)

    with pytest.raises(GraphStorageIndexError) as raised:
        service.replay_run(manifest.run_id)

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CORRUPT


def test_replay_fails_closed_when_index_omits_a_public_artifact(tmp_path) -> None:
    manifest = _manifest_with_two_public_artifacts()
    manifest, events, candidate, _ = _write_indexed_run(
        tmp_path,
        manifest=manifest,
    )
    forged_candidate = replace(
        candidate,
        artifact_records=(candidate.artifact_records[0],),
    )
    forged_store = LocalGraphStorageIndexStore(tmp_path / "missing-artifact-index")
    forged_store.write(forged_candidate)
    service = _service(tmp_path, manifest, events, forged_store)

    with pytest.raises(GraphStorageIndexError) as raised:
        service.replay_run(manifest.run_id)

    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CORRUPT


def test_graph_index_reader_rejects_missing_and_tampered_snapshots(tmp_path) -> None:
    manifest, _, _, store = _write_indexed_run(tmp_path)
    reader = GraphStorageIndexReader(store)
    restored = reader.read_for_manifest(manifest)
    assert restored.identity.run_id == manifest.run_id

    target = next((tmp_path / "graph-index").glob("index-*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["snapshot_checksum"] = "sha256:" + "0" * 64
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GraphStorageIndexError) as raised:
        reader.read_for_manifest(manifest)
    assert raised.value.code is GraphStorageIndexErrorCode.INDEX_CORRUPT


def test_production_inspection_factory_requires_the_graph_index_reader(tmp_path) -> None:
    manifest, _, _, _ = _write_indexed_run(tmp_path)
    event_storage = SimpleNamespace(
        event_store=SQLiteEventStore(tmp_path / "inspection-events.sqlite3"),
        schema_catalog=default_event_schema_catalog(),
    )

    service = build_graph_run_inspection_service(
        artifact_root=tmp_path,
        event_storage=event_storage,
        tenant_id=manifest.tenant_id,
    )

    assert isinstance(service._graph_index_reader, GraphStorageIndexReader)
    assert service.get_run_steps(manifest.run_id).steps[0]["node_instance_id"] == "analyze:1"


def test_catalog_health_counts_a_missing_graph_index_as_invalid(tmp_path) -> None:
    manifest, events, _, store = _write_indexed_run(tmp_path)
    service = _service(tmp_path, manifest, events, store)
    for path in (tmp_path / "graph-index").glob("index-*.json"):
        path.unlink()

    health = service.get_catalog_health().health

    assert health == {
        "total_runs": 1,
        "invalid_runs": 1,
        "quarantined_runs": 0,
        "graph_only": True,
    }


def test_inspection_service_requires_a_graph_index_reader() -> None:
    with pytest.raises(TypeError, match="graph_index_reader"):
        GraphRunInspectionService(".newsroom/test-runs")


def _manifest_with_two_public_artifacts():
    manifest = _manifest_with_node_binding()
    source = manifest.artifacts[0]
    binding = GraphArtifactBindingProjection.for_node(
        artifact_id="analysis-2",
        node_id=source.node_id,
        node_instance_id="analyze:1",
        attempt_id=source.attempt_id,
        evidence_ref=_SHA_C,
        evidence_source=GraphArtifactBindingEvidenceSource.WORKER_SIDE_EFFECT_INTENT,
    )
    additional = GraphTerminalArtifact(
        artifact_key="analysis-copy",
        artifact_id="analysis-2",
        ref=f"artifact://{manifest.run_id}/analysis-2",
        relative_path="nodes/analyze/analysis-copy.json",
        content_checksum=source.content_checksum,
        byte_size=source.byte_size,
        media_type=source.media_type,
        node_id=source.node_id,
        attempt_id=source.attempt_id,
        required_for_replay=True,
        required_for_publication=True,
        metadata={"graph_artifact_binding": binding.to_dict()},
    )
    terminal = replace(
        manifest.terminal,
        artifacts=(source, additional),
        manifest_hash=None,
    )
    return type(manifest)(
        terminal=terminal,
        execution_versions=manifest.execution_versions,
    )
