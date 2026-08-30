from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from framework.events import (
    GRAPH_EVENT_CONTEXT_EXTENSION,
    BusinessContext,
    EventCandidate,
    GraphEventContext,
    GraphExecutionIdentity,
    GraphEventExecutionVersion,
    GraphRunIdentity,
    GraphStageIdentity,
    ProducerIdentity,
    StoredEvent,
)
from framework.harness.artifacts import (
    GraphTerminalArtifact,
    GraphTerminalManifest,
    GraphTerminalManifestV2,
    GraphTerminalStatus,
    graph_terminal_manifest_hash,
)
from framework.harness.graph import HarnessGraphCompiler
from framework.harness.graph.execution_versions import GraphExecutionVersionManifest
from backend.research.graphs import build_paper_analysis_graph_definition
from infrastructure.storage.indexing import (
    GraphArtifactNodeBinding,
    GraphIndexDiagnosticCode,
    GraphIndexStageStatus,
    GraphStorageIndexCandidate,
    GraphStorageIndexCandidateRequest,
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    InactiveGraphStorageIndexAdapter,
    LocalGraphIndexCandidateStore,
)


_NOW = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
_CONTENT = b'{"analysis":"complete"}'
_SHA_A = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_SHA_C = "sha256:" + "c" * 64
_RUN_ID = "run-index-1"


def test_qualified_dry_run_builds_checksum_bound_graph_records(tmp_path) -> None:
    request = _request()
    adapter = _adapter(tmp_path)

    report = adapter.dry_run(request)

    assert report.qualified is True
    assert report.diagnostics == ()
    candidate = report.candidate
    assert candidate is not None
    assert candidate.identity.run_id == _RUN_ID
    assert candidate.identity.terminal_manifest_hash == request.manifest.manifest_hash
    assert candidate.event_high_watermark == 2
    assert tuple(record.stream_sequence for record in candidate.event_records) == (1, 2)
    artifact_record = candidate.artifact_records[0]
    assert artifact_record.node_id == "analyze"
    assert artifact_record.node_instance_id == "analyze:1"
    assert artifact_record.content_checksum == request.manifest.artifacts[0].content_checksum
    assert artifact_record.binding_evidence_ref == _SHA_C
    assert candidate.event_records[1].source_record_checksum == request.events[1].record_checksum
    candidate.verify_integrity()

    restored = GraphStorageIndexCandidate.from_dict(
        json.loads(json.dumps(candidate.to_dict()))
    )
    assert restored == candidate


def test_candidate_contract_rejects_nested_record_tampering(tmp_path) -> None:
    candidate = _qualified_candidate(tmp_path)
    payload = json.loads(json.dumps(candidate.to_dict()))
    payload["event_records"][1]["event_type"] = "tampered_event"

    with pytest.raises(GraphStorageIndexError) as raised:
        GraphStorageIndexCandidate.from_dict(payload)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_CORRUPT


@pytest.mark.parametrize(
    ("variant", "expected_code"),
    [
        ("missing_binding", GraphIndexDiagnosticCode.ARTIFACT_BINDING_MISSING),
        ("binding_mismatch", GraphIndexDiagnosticCode.ARTIFACT_BINDING_MISMATCH),
        ("sequence_gap", GraphIndexDiagnosticCode.EVENT_SEQUENCE_INVALID),
        (
            "graph_mismatch",
            GraphIndexDiagnosticCode.EVENT_GRAPH_IDENTITY_MISMATCH,
        ),
        ("event_tamper", GraphIndexDiagnosticCode.EVENT_INTEGRITY_INVALID),
    ],
)
def test_dry_run_returns_typed_diagnostics_without_a_candidate(
    tmp_path,
    variant: str,
    expected_code: GraphIndexDiagnosticCode,
) -> None:
    request = _invalid_request(variant)

    report = _adapter(tmp_path).dry_run(request)

    assert report.qualified is False
    assert report.candidate is None
    assert expected_code in {diagnostic.code for diagnostic in report.diagnostics}
    assert list(tmp_path.iterdir()) == []


def test_dry_run_rejects_a_tampered_terminal_manifest(tmp_path) -> None:
    request = _request()
    object.__setattr__(request.manifest.terminal, "graph_version", "2")

    report = _adapter(tmp_path).dry_run(request)

    assert report.qualified is False
    assert tuple(item.code for item in report.diagnostics) == (
        GraphIndexDiagnosticCode.MANIFEST_INTEGRITY_INVALID,
    )
    assert list(tmp_path.iterdir()) == []


def test_dry_run_rejects_an_artifact_path_escape_before_staging(tmp_path) -> None:
    manifest = _manifest()
    artifact = manifest.artifacts[0]
    object.__setattr__(artifact, "relative_path", "../outside.json")
    object.__setattr__(
        manifest,
        "manifest_hash",
        graph_terminal_manifest_hash(manifest),
    )

    report = _adapter(tmp_path).dry_run(_request(manifest=manifest))

    assert report.qualified is False
    assert GraphIndexDiagnosticCode.ARTIFACT_PATH_INVALID in {
        diagnostic.code for diagnostic in report.diagnostics
    }
    assert list(tmp_path.iterdir()) == []


def test_stage_and_read_back_are_exact_and_idempotent(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    report = adapter.dry_run(_request())

    first = adapter.stage_qualified_candidate(report)
    restored = adapter.read_back(first)
    second = adapter.stage_qualified_candidate(report)

    assert first.status is GraphIndexStageStatus.STAGED
    assert second.status is GraphIndexStageStatus.IDEMPOTENT
    assert second.candidate_ref == first.candidate_ref
    assert second.candidate_checksum == first.candidate_checksum
    assert restored == report.candidate
    assert len(tuple(tmp_path.glob("candidate-*.json"))) == 1


def test_store_rejects_same_identity_with_different_event_history(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    first = adapter.dry_run(_request())
    extended_events = (*_events(_manifest()), _event(3, _identity()))
    second = adapter.dry_run(_request(events=extended_events))
    assert first.candidate is not None
    assert second.candidate is not None
    assert first.candidate.candidate_ref == second.candidate.candidate_ref
    assert first.candidate.candidate_checksum != second.candidate.candidate_checksum

    receipt = adapter.stage_qualified_candidate(first)
    with pytest.raises(GraphStorageIndexError) as raised:
        adapter.stage_qualified_candidate(second)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_CONFLICT
    assert adapter.read_back(receipt) == first.candidate


def test_store_rejects_tampered_candidate_before_writing(tmp_path) -> None:
    candidate = _qualified_candidate(tmp_path)
    object.__setattr__(candidate, "event_high_watermark", 99)
    store = LocalGraphIndexCandidateStore(tmp_path)

    with pytest.raises(GraphStorageIndexError) as raised:
        store.stage_candidate(candidate)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_CORRUPT
    assert list(tmp_path.iterdir()) == []


def test_read_back_classifies_persisted_contract_tampering_as_corrupt(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    report = adapter.dry_run(_request())
    receipt = adapter.stage_qualified_candidate(report)
    target = next(tmp_path.glob("candidate-*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["event_records"][0]["event_type"] = "tampered_event"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GraphStorageIndexError) as raised:
        adapter.read_back(receipt)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_CORRUPT


def test_unqualified_report_cannot_be_staged(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    report = adapter.dry_run(_request(events=()))

    with pytest.raises(GraphStorageIndexError) as raised:
        adapter.stage_qualified_candidate(report)

    assert raised.value.code is GraphStorageIndexErrorCode.CANDIDATE_NOT_QUALIFIED
    assert list(tmp_path.iterdir()) == []


def _adapter(root) -> InactiveGraphStorageIndexAdapter:
    return InactiveGraphStorageIndexAdapter(LocalGraphIndexCandidateStore(root))


def _qualified_candidate(root) -> GraphStorageIndexCandidate:
    candidate = _adapter(root).dry_run(_request()).candidate
    assert candidate is not None
    return candidate


def _invalid_request(variant: str) -> GraphStorageIndexCandidateRequest:
    manifest = _manifest()
    events = _events(manifest)
    bindings = (_binding(),)
    if variant == "missing_binding":
        bindings = ()
    elif variant == "binding_mismatch":
        bindings = (_binding(attempt_id="attempt-2"),)
    elif variant == "sequence_gap":
        events = (events[0], _event(3, _identity(manifest), with_node=True))
    elif variant == "graph_mismatch":
        events = (
            events[0],
            _event(
                2,
                _identity(manifest, checksum=_SHA_B),
                with_node=True,
            ),
        )
    elif variant == "event_tamper":
        object.__setattr__(events[1].candidate, "content_checksum", _SHA_B)
    else:
        raise AssertionError(f"unknown test variant: {variant}")
    return _request(manifest=manifest, events=events, bindings=bindings)


def _request(
    *,
    manifest: GraphTerminalManifestV2 | None = None,
    events: tuple[StoredEvent, ...] | None = None,
    bindings: tuple[GraphArtifactNodeBinding, ...] | None = None,
) -> GraphStorageIndexCandidateRequest:
    actual_manifest = manifest or _manifest()
    return GraphStorageIndexCandidateRequest(
        manifest=actual_manifest,
        events=_events(actual_manifest) if events is None else events,
        artifact_bindings=(_binding(),) if bindings is None else bindings,
    )


def _manifest() -> GraphTerminalManifestV2:
    execution_versions = _execution_versions()
    terminal = GraphTerminalManifest(
        tenant_id="tenant-a",
        run_id=_RUN_ID,
        graph_id=execution_versions.graph_id,
        graph_version=execution_versions.graph_version,
        graph_schema_version=execution_versions.normalized_graph_schema_version,
        compiler_version=execution_versions.compiler_version,
        normalized_graph_checksum=execution_versions.normalized_graph_checksum,
        status=GraphTerminalStatus.SUCCEEDED,
        started_at=_NOW,
        completed_at=_NOW + timedelta(seconds=5),
        terminal_state_ref=_SHA_B,
        checkpoint_ref=f"checkpoint://{_RUN_ID}/terminal",
        terminal_node_ids=execution_versions.terminal_node_ids,
        gate_evidence_refs=(_SHA_C,),
        artifacts=(
            GraphTerminalArtifact(
                artifact_key="analysis",
                artifact_id="analysis-1",
                ref=f"artifact://{_RUN_ID}/analysis-1",
                relative_path="nodes/analyze/analysis.json",
                content_checksum=(
                    "sha256:" + sha256(_CONTENT).hexdigest()
                ),
                byte_size=len(_CONTENT),
                media_type="application/json",
                node_id="analyze",
                attempt_id="attempt-1",
                required_for_replay=True,
                required_for_publication=True,
                metadata={"producer_revision": "research@1"},
            ),
        ),
    )
    return GraphTerminalManifestV2(
        terminal=terminal,
        execution_versions=execution_versions,
    )


def _binding(*, attempt_id: str = "attempt-1") -> GraphArtifactNodeBinding:
    return GraphArtifactNodeBinding(
        artifact_id="analysis-1",
        node_id="analyze",
        node_instance_id="analyze:1",
        attempt_id=attempt_id,
        evidence_ref=_SHA_C,
    )


def _identity(
    manifest: GraphTerminalManifestV2 | None = None,
    *,
    checksum: str | None = None,
) -> GraphRunIdentity:
    source = manifest or _manifest()
    return GraphRunIdentity(
        run_id=source.run_id,
        graph_id=source.graph_id,
        graph_version=source.graph_version,
        graph_ref=f"{source.graph_id}@{source.graph_version}",
        graph_checksum=checksum or source.normalized_graph_checksum,
    )


def _events(manifest: GraphTerminalManifestV2) -> tuple[StoredEvent, ...]:
    identity = _identity(manifest)
    return (
        _event(1, identity),
        _event(2, identity, with_node=True),
    )


def _execution_versions() -> GraphExecutionVersionManifest:
    graph = HarnessGraphCompiler().compile(
        build_paper_analysis_graph_definition()
    ).graph
    return GraphExecutionVersionManifest.from_normalized_graph(graph)


def _event(
    sequence: int,
    identity: GraphRunIdentity,
    *,
    with_node: bool = False,
    with_activity: bool = False,
) -> StoredEvent:
    execution_identity = (
        GraphExecutionIdentity(
            run_id=identity.run_id,
            graph_id=identity.graph_id,
            graph_version=identity.graph_version,
            graph_ref=identity.graph_ref,
            graph_checksum=identity.graph_checksum,
            node_id="analyze",
            node_instance_id="analyze:1",
            activity_id="activity-analyze-1",
            attempt=1,
        )
        if with_activity
        else None
    )
    context = GraphEventContext(
        identity=identity,
        execution_version=GraphEventExecutionVersion(
            graph_schema_version="newsroom.normalized-harness-graph/v3",
            compiler_version="3",
            normalized_graph_checksum=identity.graph_checksum,
        ),
        stage_identity=(
            GraphStageIdentity(
                run_id=identity.run_id,
                graph_id=identity.graph_id,
                graph_version=identity.graph_version,
                graph_ref=identity.graph_ref,
                graph_checksum=identity.graph_checksum,
                node_id="analyze",
                node_instance_id="analyze:1",
            )
            if with_node and execution_identity is None
            else None
        ),
        execution_identity=execution_identity,
    )
    candidate = EventCandidate(
        event_id=f"evt-index-{sequence}-{identity.graph_checksum[-1]}",
        event_type=(
            "harness_graph_initialized"
            if sequence == 1
            else "harness_graph_decision_committed"
        ),
        data_schema="newsroom.harness-graph-control-commit/v1",
        source="io.newsroom.harness.control-plane",
        occurred_at=_NOW + timedelta(seconds=sequence),
        stream_id=f"run:{identity.run_id}",
        correlation_id=identity.run_id,
        business_context=BusinessContext(
            run_id=identity.run_id,
            graph_id=identity.graph_id,
            graph_version=identity.graph_version,
            graph_ref=f"{identity.graph_id}@{identity.graph_version}",
            graph_checksum=identity.graph_checksum,
            execution_identity=context.execution_identity,
            stage_id=context.node_id,
            node_instance_id=context.node_instance_id,
        ),
        producer=ProducerIdentity(
            component="framework.harness.control_plane",
            version="1",
        ),
        tenant_id="tenant-a",
        payload={"commit": {"sequence": sequence}},
        extensions={GRAPH_EVENT_CONTEXT_EXTENSION: context.to_dict()},
    )
    return StoredEvent(
        candidate=candidate,
        observed_at=_NOW + timedelta(seconds=sequence, microseconds=1),
        stream_sequence=sequence,
    )
