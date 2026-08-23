from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from business.research.graphs import build_paper_analysis_graph_definition
from framework.harness.artifacts import (
    ArtifactWriteRequest,
    GraphArtifactPhysicalLifecyclePort,
    GraphTerminalManifest,
    GraphTerminalManifestV2,
)
from framework.harness.graph import GraphExecutionVersionManifest, HarnessGraphCompiler
from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcDetachRequest,
    ArtifactCatalogRegistrationRequest,
    ArtifactLifecycleAuthorization,
    ArtifactLifecycleAuthorityKind,
    ArtifactReferenceRetirementReason,
    ArtifactReferenceRetirementRequest,
    ArtifactVerificationReceipt,
)
from framework.harness.artifacts.governance import (
    GraphArtifactGcOperationIntent,
    GraphArtifactPhysicalDeleteRequest,
)
from framework.harness.runtime.materializer import RESULT_PAYLOAD_SCHEMA
from framework.harness.runtime.result_canonical import (
    serialize_candidate,
    sha256_checksum,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    ArtifactRecord,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.research import (
    FilesystemGraphArtifactLifecycle,
    FilesystemHarnessArtifactPort,
)
from infrastructure.storage.artifacts import LocalJsonArtifactCatalog


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
ARTIFACT_TYPE = "graph-result-" + "a" * 64
CHECKSUM = "sha256:" + "c" * 64


def _write_graph_result(
    root: Path,
    *,
    artifact_class: ArtifactClass = ArtifactClass.EVIDENCE,
    retention_class: RetentionClass = RetentionClass.EVIDENCE,
    required_for_publication: bool = False,
    required_for_replay: bool = False,
) -> tuple[
    FilesystemHarnessArtifactPort,
    LocalJsonArtifactCatalog,
    ArtifactRecord,
]:
    port = FilesystemHarnessArtifactPort(root)
    candidate, candidate_bytes = serialize_candidate(
        {"data": "verified graph result"},
        "application/json",
    )
    candidate_checksum = sha256_checksum(candidate_bytes)
    metadata = {
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "graph_id": "research-graph",
        "node_id": "collect-evidence",
        "attempt_id": "attempt-1",
        "candidate_checksum": candidate_checksum,
        "graph_result_ref_only": True,
        "identity_checksum": "sha256:" + "a" * 64,
        "required_for_replay": required_for_replay,
        "required_for_publication": required_for_publication,
    }
    with port.bind_run("run-1"):
        ref = port.write_artifact(
            ArtifactWriteRequest(
                artifact_type=ARTIFACT_TYPE,
                payload={
                    "schema": RESULT_PAYLOAD_SCHEMA,
                    "candidate_checksum": candidate_checksum,
                    "candidate_bytes": len(candidate_bytes),
                    "media_type": "application/json",
                    "encoding": "json",
                    "value": candidate,
                },
                metadata=metadata,
            )
        )
    staged = port.list_staged_artifacts("run-1")
    execution_versions = _execution_versions()
    port.write_terminal_manifest(
        GraphTerminalManifestV2(
            terminal=GraphTerminalManifest(
                tenant_id="tenant-1",
                run_id="run-1",
                graph_id=execution_versions.graph_id,
                graph_version=execution_versions.graph_version,
                graph_schema_version=execution_versions.normalized_graph_schema_version,
                compiler_version=execution_versions.compiler_version,
                normalized_graph_checksum=execution_versions.normalized_graph_checksum,
                status="succeeded",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=2),
                terminal_state_ref="sha256:" + "e" * 64,
                checkpoint_ref="graph-state://run-1/terminal",
                terminal_node_ids=execution_versions.terminal_node_ids,
                gate_evidence_refs=("sha256:" + "f" * 64,),
                artifacts=staged,
            ),
            execution_versions=execution_versions,
        )
    )
    record = ArtifactRecord(
        ref=ref.ref,
        artifact_id="result-" + "b" * 64,
        artifact_type=ARTIFACT_TYPE,
        content_checksum=candidate_checksum,
        byte_size=len(candidate_bytes),
        media_type="application/json",
        artifact_class=artifact_class,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="research-graph",
        node_id="collect-evidence",
        attempt_id="attempt-1",
        producer_revision="research-worker@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=retention_class,
        expires_at=NOW + timedelta(days=1),
        required_for_replay=required_for_replay,
        required_for_publication=required_for_publication,
        created_at=NOW,
    )
    catalog = LocalJsonArtifactCatalog(root / "_records" / "graph_artifact_catalog")
    catalog.register(
        request=_registration(record),
    )
    return port, catalog, record


def _execution_versions() -> GraphExecutionVersionManifest:
    graph = HarnessGraphCompiler().compile(
        build_paper_analysis_graph_definition()
    ).graph
    return GraphExecutionVersionManifest.from_normalized_graph(graph)


def _registration(record: ArtifactRecord) -> ArtifactCatalogRegistrationRequest:
    return ArtifactCatalogRegistrationRequest.from_verified_record(
        record,
        verified_at=NOW + timedelta(seconds=1),
    )


def _delete_request(
    catalog: LocalJsonArtifactCatalog,
    record: ArtifactRecord,
) -> GraphArtifactPhysicalDeleteRequest:
    retirement_time = NOW + timedelta(days=2)
    claim = catalog.get_claim(
        tenant_id=record.tenant_id,
        run_id=record.run_id,
        artifact_id=record.artifact_id,
    )
    logical_reference = catalog.list_references(claim.entry_id)[0]
    authorization = ArtifactLifecycleAuthorization.create(
        kind=ArtifactLifecycleAuthorityKind.TERMINAL_RUN,
        tenant_id=record.tenant_id,
        owner_run_id=record.run_id,
        owner_id=record.artifact_id,
        lifecycle_ref="run-lifecycle://run-1/terminal",
        observed_at=retirement_time - timedelta(seconds=1),
        policy_version="graph-artifact-policy@1",
    )
    catalog.retire_reference(
        ArtifactReferenceRetirementRequest.create(
            reference=logical_reference,
            authorization=authorization,
            reason=ArtifactReferenceRetirementReason.RETENTION_EXPIRED,
            requested_at=retirement_time,
        )
    )
    plan = catalog.plan_gc(now=retirement_time, tenant_id=record.tenant_id)
    decision = plan.decisions[0]
    intent = GraphArtifactGcOperationIntent.create(
        tenant_id=record.tenant_id,
        plan_checksum=plan.plan_checksum,
        catalog_snapshot_checksum=plan.catalog_snapshot_checksum,
        policy_version=plan.policy_version,
        decision=decision,
        entry=catalog.get(claim.entry_id),
        claims=(claim,),
        references=(),
        prepared_at=retirement_time,
    )
    detach_request = ArtifactCatalogGcDetachRequest.create(
        plan_checksum=plan.plan_checksum,
        catalog_snapshot_checksum=plan.catalog_snapshot_checksum,
        decision=decision,
        requested_at=retirement_time,
    )
    detach_receipt = catalog.detach_gc_candidate(detach_request)
    return GraphArtifactPhysicalDeleteRequest.create(
        operation_id=intent.operation_id,
        plan_checksum=plan.plan_checksum,
        decision_checksum=decision.decision_checksum,
        intent_checksum=intent.intent_checksum,
        record=record,
        detach_receipt=detach_receipt,
        requested_at=retirement_time,
    )


def _fabricated_request(record: ArtifactRecord, *, suffix: str) -> GraphArtifactPhysicalDeleteRequest:
    verification = ArtifactVerificationReceipt.for_record(
        record,
        verified_at=NOW + timedelta(seconds=1),
    )
    entry = ArtifactCatalogEntry.from_verified_record(record, verification)
    claim = ArtifactCatalogClaim.for_record(record, entry_id=entry.entry_id)
    detached_at = NOW + timedelta(days=2)
    receipt = ArtifactCatalogGcDetachReceipt.create(
        request_checksum=CHECKSUM,
        entry=entry,
        claims=(claim,),
        references=(),
        detached_at=detached_at,
    )
    return GraphArtifactPhysicalDeleteRequest.create(
        operation_id=f"graph-artifact-gc://tenant-1/{suffix}",
        plan_checksum=CHECKSUM,
        decision_checksum=CHECKSUM,
        intent_checksum=CHECKSUM,
        record=record,
        detach_receipt=receipt,
        requested_at=detached_at,
    )


def _source_path(port: FilesystemHarnessArtifactPort) -> Path:
    manifest = port.read_terminal_manifest("run-1")
    artifact = manifest.artifact(ARTIFACT_TYPE)
    assert artifact is not None
    return port.root / "run-1" / artifact.relative_path


def _state_path(root: Path) -> Path:
    paths = tuple(root.rglob("state.json"))
    assert len(paths) == 1
    return paths[0]


def _quarantine_path(root: Path) -> Path:
    paths = tuple(root.rglob("payload.quarantine"))
    assert len(paths) == 1
    return paths[0]


def test_lifecycle_quarantines_and_purges_idempotently_after_restart(tmp_path) -> None:
    root = tmp_path / "runs"
    port, catalog, record = _write_graph_result(root)
    source = _source_path(port)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))

    quarantine = lifecycle.quarantine(request)

    assert isinstance(lifecycle, GraphArtifactPhysicalLifecyclePort)
    assert quarantine.ref == record.ref
    assert quarantine.content_checksum == record.content_checksum
    assert source.exists() is False
    manifest = port.read_terminal_manifest("run-1")
    assert manifest.artifact(ARTIFACT_TYPE) is None
    state_text = _state_path(root).read_text(encoding="utf-8")
    assert "verified graph result" not in state_text
    assert str(root) not in state_text

    restarted = FilesystemGraphArtifactLifecycle(
        root,
        clock=lambda: NOW + timedelta(days=3),
    )
    assert restarted.quarantine(request) == quarantine
    quarantine_path = _quarantine_path(root)
    deletion = restarted.purge(quarantine)
    assert quarantine_path.exists() is False
    assert restarted.purge(quarantine) == deletion
    assert restarted.quarantine(request) == quarantine


def test_two_executors_converge_on_one_quarantine_and_purge(tmp_path) -> None:
    root = tmp_path / "runs"
    _, catalog, record = _write_graph_result(root)
    request = _delete_request(catalog, record)
    lifecycles = (
        FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2)),
        FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2)),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        quarantines = tuple(
            executor.map(lambda lifecycle: lifecycle.quarantine(request), lifecycles)
        )
    with ThreadPoolExecutor(max_workers=2) as executor:
        deletions = tuple(
            executor.map(lambda lifecycle: lifecycle.purge(quarantines[0]), lifecycles)
        )

    assert quarantines[0] == quarantines[1]
    assert deletions[0] == deletions[1]


@pytest.mark.parametrize("target", ["payload", "manifest"])
def test_lifecycle_rejects_tampered_physical_evidence_without_detach(
    tmp_path,
    target: str,
) -> None:
    root = tmp_path / "runs"
    port, catalog, record = _write_graph_result(root)
    source = _source_path(port)
    request = _delete_request(catalog, record)
    if target == "payload":
        source.write_bytes(source.read_bytes() + b" ")
    else:
        manifest = port.read_terminal_manifest("run-1")
        artifact = manifest.artifact(ARTIFACT_TYPE)
        assert artifact is not None
        tampered_artifact = replace(
            artifact,
            content_checksum="sha256:" + "d" * 64,
        )
        tampered = replace(
            manifest,
            terminal=replace(
                manifest.terminal,
                artifacts=(tampered_artifact,),
                manifest_hash=None,
            ),
            manifest_hash=None,
        )
        port.manager.write_json("run-1", "manifest.json", tampered.to_dict())

    with pytest.raises(GraphArtifactResultError) as failure:
        FilesystemGraphArtifactLifecycle(root).quarantine(request)

    assert failure.value.error_code is GraphArtifactResultErrorCode.GC_OPERATION_FAILED
    assert source.exists()
    assert port.read_terminal_manifest("run-1").artifact(ARTIFACT_TYPE) is not None
    assert tuple(root.rglob("state.json")) == ()


@pytest.mark.parametrize("target", ["public", "cross_run", "arbitrary", "unexpired"])
def test_lifecycle_rejects_unauthorized_targets(tmp_path, target: str) -> None:
    root = tmp_path / "runs"
    port, _, record = _write_graph_result(root)
    if target == "public":
        candidate = replace(
            record,
            artifact_class=ArtifactClass.REPORT,
            retention_class=RetentionClass.REPORT,
            required_for_publication=True,
        )
    elif target == "cross_run":
        candidate = replace(record, run_id="run-2")
    elif target == "arbitrary":
        candidate = replace(record, ref="file://run-1/arbitrary")
    else:
        candidate = replace(record, expires_at=NOW + timedelta(days=10))
    request = _fabricated_request(candidate, suffix=target)

    with pytest.raises(GraphArtifactResultError) as failure:
        FilesystemGraphArtifactLifecycle(root).quarantine(request)

    assert failure.value.error_code in {
        GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
        GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID,
    }
    assert _source_path(port).exists()
    assert tuple(root.rglob("state.json")) == ()


def test_lifecycle_rejects_symlink_target_without_touching_victim(tmp_path) -> None:
    root = tmp_path / "runs"
    port, catalog, record = _write_graph_result(root)
    source = _source_path(port)
    request = _delete_request(catalog, record)
    victim = tmp_path / "victim.json"
    victim.write_text("do not delete", encoding="utf-8")
    source.unlink()
    try:
        os.symlink(victim, source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(GraphArtifactResultError) as failure:
        FilesystemGraphArtifactLifecycle(root).quarantine(request)

    assert failure.value.error_code is GraphArtifactResultErrorCode.GC_OPERATION_FAILED
    assert victim.read_text(encoding="utf-8") == "do not delete"
    assert source.is_symlink()


def test_lifecycle_state_tamper_fails_closed_without_purging(tmp_path) -> None:
    root = tmp_path / "runs"
    _, catalog, record = _write_graph_result(root)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    quarantine = lifecycle.quarantine(request)
    quarantine_path = _quarantine_path(root)
    state_path = _state_path(root)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["physical_byte_size"] += 1
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(GraphArtifactResultError) as failure:
        lifecycle.purge(quarantine)

    assert failure.value.error_code is GraphArtifactResultErrorCode.GC_OPERATION_FAILED
    assert quarantine_path.exists()


def test_relative_artifact_root_uses_the_same_verified_locks(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = Path("runs")
    _, catalog, record = _write_graph_result(root)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(
        root,
        clock=lambda: NOW + timedelta(days=2),
    )

    quarantine = lifecycle.quarantine(request)
    deletion = lifecycle.purge(quarantine)

    assert deletion.ref == record.ref
    assert tuple((tmp_path / "runs").rglob("payload.quarantine")) == ()


def test_restart_recovers_after_manifest_detach_before_move(tmp_path, monkeypatch) -> None:
    root = tmp_path / "runs"
    port, catalog, record = _write_graph_result(root)
    source = _source_path(port)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    monkeypatch.setattr(
        lifecycle,
        "_atomic_move",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")),
    )

    with pytest.raises(GraphArtifactResultError):
        lifecycle.quarantine(request)

    assert source.exists()
    assert port.read_terminal_manifest("run-1").artifact(ARTIFACT_TYPE) is None
    restarted = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    assert restarted.quarantine(request).ref == record.ref


def test_restart_recovers_after_move_before_receipt(tmp_path, monkeypatch) -> None:
    root = tmp_path / "runs"
    _, catalog, record = _write_graph_result(root)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    original_write = lifecycle._write_state
    calls = 0

    def fail_second_write(path, state):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        original_write(path, state)

    monkeypatch.setattr(lifecycle, "_write_state", fail_second_write)

    with pytest.raises(GraphArtifactResultError):
        lifecycle.quarantine(request)

    assert _quarantine_path(root).exists()
    restarted = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    assert restarted.quarantine(request).ref == record.ref


def test_restart_recovers_after_purge_before_deletion_receipt(tmp_path, monkeypatch) -> None:
    root = tmp_path / "runs"
    _, catalog, record = _write_graph_result(root)
    request = _delete_request(catalog, record)
    lifecycle = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=2))
    quarantine = lifecycle.quarantine(request)
    quarantine_path = _quarantine_path(root)
    monkeypatch.setattr(
        lifecycle,
        "_write_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")),
    )

    with pytest.raises(GraphArtifactResultError):
        lifecycle.purge(quarantine)

    assert quarantine_path.exists() is False
    restarted = FilesystemGraphArtifactLifecycle(root, clock=lambda: NOW + timedelta(days=3))
    deletion = restarted.purge(quarantine)
    assert deletion.ref == record.ref
    assert restarted.purge(quarantine) == deletion
