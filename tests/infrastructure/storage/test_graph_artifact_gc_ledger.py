from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDecision,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcPlan,
    ArtifactCatalogGcReason,
    ArtifactLogicalReference,
    ArtifactReferenceKind,
    ArtifactVerificationReceipt,
)
from framework.harness.artifacts.governance import (
    GraphArtifactDeletionReceipt,
    GraphArtifactGcOperation,
    GraphArtifactGcOperationIntent,
    GraphArtifactGcOperationState,
    GraphArtifactGovernanceLedgerPort,
    GraphArtifactPhysicalDeleteRequest,
    GraphArtifactQuarantineReceipt,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.storage.artifacts import SQLiteGraphResultStore


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64
SNAPSHOT_CHECKSUM = "sha256:" + "b" * 64


def test_gc_plan_operation_transitions_and_tombstone_survive_restart(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    plan, operations = _operation_chain()
    prepared, detached, quarantined, purged, completed = operations

    assert isinstance(store, GraphArtifactGovernanceLedgerPort)
    assert store.put_gc_plan(tenant_id="tenant-1", plan=plan) == plan
    assert store.put_gc_plan(tenant_id="tenant-1", plan=plan) == plan
    assert store.get_gc_plan(
        tenant_id="tenant-2",
        plan_checksum=plan.plan_checksum,
    ) is None
    assert store.put_gc_operation(prepared) == prepared
    assert store.put_gc_operation(prepared) == prepared
    current = prepared
    for candidate in (detached, quarantined, purged, completed):
        current = store.compare_and_set_gc_operation(
            candidate,
            expected_checksum=current.operation_checksum,
        )
        assert current == candidate

    restarted = SQLiteGraphResultStore(database, clock=lambda: NOW)
    assert restarted.get_gc_operation(
        tenant_id="tenant-1",
        operation_id=completed.operation_id,
    ) == completed
    tombstone = restarted.get_gc_tombstone(
        tenant_id="tenant-1",
        operation_id=completed.operation_id,
    )
    assert tombstone is not None
    assert tombstone.operation_id == completed.operation_id
    assert restarted.list_gc_operations(
        tenant_id="tenant-1",
        include_completed=False,
    ) == ()
    assert restarted.list_gc_operations(
        tenant_id="tenant-1",
        include_completed=True,
    ) == (completed,)


def test_gc_operation_compare_and_set_allows_only_one_concurrent_transition(
    tmp_path,
) -> None:
    store = SQLiteGraphResultStore(
        tmp_path / "graph-results.sqlite3",
        clock=lambda: NOW,
    )
    _, operations = _operation_chain()
    prepared, detached, _, _, _ = operations
    stale = GraphArtifactGcOperation.create(
        operation_id=prepared.operation_id,
        state=GraphArtifactGcOperationState.STALE,
        intent=prepared.intent,
        request=None,
        quarantine=None,
        deletion=None,
        error_code=None,
        updated_at=prepared.updated_at + timedelta(seconds=1),
    )
    store.put_gc_operation(prepared)

    def commit(candidate: GraphArtifactGcOperation):
        try:
            return store.compare_and_set_gc_operation(
                candidate,
                expected_checksum=prepared.operation_checksum,
            )
        except GraphArtifactResultError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(commit, (detached, stale)))

    assert sum(isinstance(item, GraphArtifactGcOperation) for item in outcomes) == 1
    assert GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT in outcomes


def test_gc_operation_invalid_skip_and_sql_tamper_fail_closed(tmp_path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    _, operations = _operation_chain()
    prepared, _, _, _, completed = operations
    store.put_gc_operation(prepared)

    with pytest.raises(GraphArtifactResultError) as skipped:
        store.compare_and_set_gc_operation(
            completed,
            expected_checksum=prepared.operation_checksum,
        )
    assert skipped.value.error_code is GraphArtifactResultErrorCode.GC_OPERATION_FAILED
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE graph_artifact_gc_operations "
            "SET operation_json = '{\"tampered\":true}'"
        )
        connection.commit()
    with pytest.raises(GraphArtifactResultError) as tampered:
        store.get_gc_operation(
            tenant_id="tenant-1",
            operation_id=prepared.operation_id,
        )
    assert tampered.value.error_code is GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED


def _operation_chain() -> tuple[
    ArtifactCatalogGcPlan,
    tuple[
        GraphArtifactGcOperation,
        GraphArtifactGcOperation,
        GraphArtifactGcOperation,
        GraphArtifactGcOperation,
        GraphArtifactGcOperation,
    ],
]:
    entry, claim, logical_reference = _catalog_models()
    decision = ArtifactCatalogGcDecision(
        entry_id=entry.entry_id,
        tenant_id=entry.identity.tenant_id,
        ref=entry.record.ref,
        action=ArtifactCatalogGcAction.DELETE_CANDIDATE,
        reason=ArtifactCatalogGcReason.EXPIRED_UNREFERENCED,
        active_reference_ids=(),
        byte_size=entry.record.byte_size,
        claim_ids=(claim.claim_id,),
        reference_ids=(logical_reference.reference_id,),
    )
    plan = ArtifactCatalogGcPlan.create(
        generated_at=NOW,
        decisions=(decision,),
        catalog_snapshot_checksum=SNAPSHOT_CHECKSUM,
    )
    intent = GraphArtifactGcOperationIntent.create(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        catalog_snapshot_checksum=plan.catalog_snapshot_checksum,
        policy_version=plan.policy_version,
        decision=decision,
        entry=entry,
        claims=(claim,),
        references=(logical_reference,),
        prepared_at=NOW + timedelta(seconds=1),
    )
    prepared = GraphArtifactGcOperation.create(
        operation_id=intent.operation_id,
        state=GraphArtifactGcOperationState.PREPARED,
        intent=intent,
        request=None,
        quarantine=None,
        deletion=None,
        error_code=None,
        updated_at=NOW + timedelta(seconds=1),
    )
    detach = ArtifactCatalogGcDetachReceipt.create(
        request_checksum="sha256:" + "c" * 64,
        entry=entry,
        claims=(claim,),
        references=(logical_reference,),
        detached_at=NOW + timedelta(seconds=2),
    )
    request = GraphArtifactPhysicalDeleteRequest.create(
        operation_id=intent.operation_id,
        plan_checksum=plan.plan_checksum,
        decision_checksum=decision.decision_checksum,
        intent_checksum=intent.intent_checksum,
        record=entry.record,
        detach_receipt=detach,
        requested_at=NOW + timedelta(seconds=2),
    )
    detached = GraphArtifactGcOperation.create(
        operation_id=intent.operation_id,
        state=GraphArtifactGcOperationState.CATALOG_DETACHED,
        intent=intent,
        request=request,
        quarantine=None,
        deletion=None,
        error_code=None,
        updated_at=NOW + timedelta(seconds=2),
    )
    quarantine = GraphArtifactQuarantineReceipt.create(
        operation_id=intent.operation_id,
        ref=entry.record.ref,
        content_checksum=entry.record.content_checksum,
        byte_size=entry.record.byte_size,
        quarantined_at=NOW + timedelta(seconds=3),
    )
    quarantined = GraphArtifactGcOperation.create(
        operation_id=intent.operation_id,
        state=GraphArtifactGcOperationState.QUARANTINED,
        intent=intent,
        request=request,
        quarantine=quarantine,
        deletion=None,
        error_code=None,
        updated_at=NOW + timedelta(seconds=3),
    )
    deletion = GraphArtifactDeletionReceipt.create(
        operation_id=intent.operation_id,
        quarantine_receipt_checksum=quarantine.receipt_checksum,
        ref=entry.record.ref,
        content_checksum=entry.record.content_checksum,
        byte_size=entry.record.byte_size,
        deleted_at=NOW + timedelta(seconds=4),
    )
    purged = GraphArtifactGcOperation.create(
        operation_id=intent.operation_id,
        state=GraphArtifactGcOperationState.PURGED,
        intent=intent,
        request=request,
        quarantine=quarantine,
        deletion=deletion,
        error_code=None,
        updated_at=NOW + timedelta(seconds=4),
    )
    completed = GraphArtifactGcOperation.create(
        operation_id=intent.operation_id,
        state=GraphArtifactGcOperationState.COMPLETED,
        intent=intent,
        request=request,
        quarantine=quarantine,
        deletion=deletion,
        error_code=None,
        updated_at=NOW + timedelta(seconds=5),
    )
    return plan, (prepared, detached, quarantined, purged, completed)


def _catalog_models() -> tuple[
    ArtifactCatalogEntry,
    ArtifactCatalogClaim,
    ArtifactLogicalReference,
]:
    record = ArtifactRecord(
        ref="artifact://run-1/artifact-1",
        artifact_id="artifact-1",
        artifact_type="node_result",
        content_checksum=CHECKSUM,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="research-graph",
        node_id="collect-evidence",
        attempt_id="attempt-1",
        producer_revision="research-worker@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW - timedelta(seconds=1),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW - timedelta(days=1),
    )
    verification = ArtifactVerificationReceipt.for_record(
        record,
        verified_at=record.created_at + timedelta(seconds=1),
    )
    entry = ArtifactCatalogEntry.from_verified_record(record, verification)
    claim = ArtifactCatalogClaim.for_record(record, entry_id=entry.entry_id)
    logical_reference = ArtifactLogicalReference.create(
        entry_id=entry.entry_id,
        tenant_id=record.tenant_id,
        owner_run_id=record.run_id,
        owner_id=record.artifact_id,
        kind=ArtifactReferenceKind.EVIDENCE,
        created_at=record.created_at,
    )
    return entry, claim, logical_reference
