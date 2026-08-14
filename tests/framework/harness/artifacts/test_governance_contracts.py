from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDecision,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcReason,
    ArtifactCatalogIdentity,
    ArtifactLogicalReference,
    ArtifactReferenceKind,
    ArtifactVerificationReceipt,
)
from framework.harness.artifacts.governance import (
    DailyGraphArtifactCostReport,
    GraphArtifactAlert,
    GraphArtifactAlertKind,
    GraphArtifactAlertStatus,
    GraphArtifactCostAggregate,
    GraphArtifactCostDimension,
    GraphArtifactDeletionReceipt,
    GraphArtifactDeletionTombstone,
    GraphArtifactGcOperation,
    GraphArtifactGcOperationIntent,
    GraphArtifactGcOperationState,
    GraphArtifactPhysicalDeleteRequest,
    GraphArtifactQuarantineReceipt,
    GraphArtifactQuotaScope,
    GraphArtifactQuotaSnapshot,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    GraphArtifactUsageReason,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    ResultSensitivity,
    RetentionClass,
)


DAY = datetime(2026, 8, 14, tzinfo=UTC)
NOW = DAY + timedelta(hours=8)
CHECKSUM = "sha256:" + "a" * 64
PLAN_CHECKSUM = "sha256:" + "b" * 64


def _record() -> ArtifactRecord:
    return ArtifactRecord(
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
        created_at=DAY,
    )


def _catalog_models() -> tuple[
    ArtifactCatalogEntry,
    ArtifactCatalogClaim,
    ArtifactLogicalReference,
]:
    record = _record()
    verification = ArtifactVerificationReceipt.for_record(
        record,
        verified_at=DAY + timedelta(seconds=1),
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


def _delete_request() -> tuple[
    GraphArtifactGcOperationIntent,
    GraphArtifactPhysicalDeleteRequest,
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
    detach = ArtifactCatalogGcDetachReceipt.create(
        request_checksum="sha256:" + "c" * 64,
        entry=entry,
        claims=(claim,),
        references=(logical_reference,),
        detached_at=NOW,
    )
    intent = GraphArtifactGcOperationIntent.create(
        tenant_id=entry.identity.tenant_id,
        plan_checksum=PLAN_CHECKSUM,
        catalog_snapshot_checksum=CHECKSUM,
        policy_version="graph-artifact-policy@1",
        decision=decision,
        entry=entry,
        claims=(claim,),
        references=(logical_reference,),
        prepared_at=NOW - timedelta(seconds=1),
    )
    request = GraphArtifactPhysicalDeleteRequest.create(
        operation_id=intent.operation_id,
        plan_checksum=PLAN_CHECKSUM,
        decision_checksum=decision.decision_checksum,
        intent_checksum=intent.intent_checksum,
        record=entry.record,
        detach_receipt=detach,
        requested_at=NOW,
    )
    return intent, request


def test_usage_fact_is_deterministic_exact_sanitized_and_round_trips() -> None:
    values = {
        "kind": GraphArtifactUsageKind.MATERIALIZATION,
        "outcome": GraphArtifactUsageOutcome.SUCCEEDED,
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "graph_id": "research-graph",
        "node_id": "collect-evidence",
        "artifact_class": ArtifactClass.EVIDENCE,
        "retention_class": RetentionClass.EVIDENCE,
        "policy_version": "graph-artifact-policy@1",
        "operation_id": "materialization://attempt-1",
        "logical_bytes": 17,
        "physical_bytes": 17,
        "object_count": 1,
        "reason_code": GraphArtifactUsageReason.MATERIALIZED_RESULT.value,
        "occurred_at": NOW,
    }
    first = GraphArtifactUsageFact.create(**values)
    second = GraphArtifactUsageFact.create(**values)

    assert first == second
    assert GraphArtifactUsageFact.from_dict(first.to_dict()) == first
    with pytest.raises(GraphArtifactResultError) as unknown:
        GraphArtifactUsageFact.from_dict({**first.to_dict(), "payload": "secret"})
    assert unknown.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID
    with pytest.raises(GraphArtifactResultError) as uncontrolled:
        GraphArtifactUsageFact.create(**{**values, "reason_code": "C:/secret/path"})
    assert uncontrolled.value.details == {"field": "usage.reason_code"}
    assert "secret" not in str(uncontrolled.value).casefold()


def test_usage_fact_operation_identity_conflicts_on_changed_outcome() -> None:
    succeeded = GraphArtifactUsageFact.create(
        kind=GraphArtifactUsageKind.CONTEXT_LOAD,
        outcome=GraphArtifactUsageOutcome.SUCCEEDED,
        tenant_id="tenant-1",
        policy_version="graph-artifact-policy@1",
        operation_id="context-load://plan-1",
        occurred_at=NOW,
    )
    failed = GraphArtifactUsageFact.create(
        kind=GraphArtifactUsageKind.CONTEXT_LOAD,
        outcome=GraphArtifactUsageOutcome.FAILED,
        tenant_id="tenant-1",
        policy_version="graph-artifact-policy@1",
        operation_id="context-load://plan-1",
        occurred_at=NOW,
        reason_code=GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED.value,
    )

    assert failed.fact_id == succeeded.fact_id
    assert failed.fact_checksum != succeeded.fact_checksum


@pytest.mark.parametrize(
    ("scope", "run_id", "artifact_class"),
    [
        (GraphArtifactQuotaScope.TENANT, None, None),
        (GraphArtifactQuotaScope.RUN, "run-1", None),
        (GraphArtifactQuotaScope.ARTIFACT_CLASS, None, ArtifactClass.EVIDENCE),
    ],
)
def test_quota_snapshots_are_dimensioned_and_round_trip(
    scope: GraphArtifactQuotaScope,
    run_id: str | None,
    artifact_class: ArtifactClass | None,
) -> None:
    snapshot = GraphArtifactQuotaSnapshot.create(
        scope=scope,
        tenant_id="tenant-1",
        run_id=run_id,
        artifact_class=artifact_class,
        charged_bytes=17,
        charged_objects=1,
        pending_bytes=0,
        pending_objects=0,
        limit_bytes=100,
        limit_objects=10,
        captured_at=NOW,
    )

    assert GraphArtifactQuotaSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_physical_gc_contracts_bind_every_receipt_to_one_operation() -> None:
    intent, request = _delete_request()
    quarantine = GraphArtifactQuarantineReceipt.create(
        operation_id=request.operation_id,
        ref=request.record.ref,
        content_checksum=request.record.content_checksum,
        byte_size=request.record.byte_size,
        quarantined_at=NOW + timedelta(seconds=1),
    )
    deletion = GraphArtifactDeletionReceipt.create(
        operation_id=request.operation_id,
        quarantine_receipt_checksum=quarantine.receipt_checksum,
        ref=quarantine.ref,
        content_checksum=quarantine.content_checksum,
        byte_size=quarantine.byte_size,
        deleted_at=NOW + timedelta(seconds=2),
    )
    operation = GraphArtifactGcOperation.create(
        operation_id=request.operation_id,
        state=GraphArtifactGcOperationState.COMPLETED,
        intent=intent,
        request=request,
        quarantine=quarantine,
        deletion=deletion,
        error_code=None,
        updated_at=NOW + timedelta(seconds=3),
    )

    assert GraphArtifactPhysicalDeleteRequest.from_dict(request.to_dict()) == request
    assert GraphArtifactGcOperation.from_dict(operation.to_dict()) == operation
    tombstone = GraphArtifactDeletionTombstone.from_completed_operation(operation)
    assert GraphArtifactDeletionTombstone.from_dict(tombstone.to_dict()) == tombstone
    with pytest.raises(GraphArtifactResultError):
        replace(operation, quarantine=replace(quarantine, byte_size=18))


def test_cost_report_is_reproducible_multidimensional_and_exact() -> None:
    dimension = GraphArtifactCostDimension(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="research-graph",
        node_id="collect-evidence",
        artifact_class=ArtifactClass.EVIDENCE,
        policy_version="graph-artifact-policy@1",
    )
    aggregate = GraphArtifactCostAggregate.create(
        dimension=dimension,
        logical_bytes=34,
        logical_count=2,
        unique_physical_bytes=17,
        unique_physical_count=1,
        expired_bytes=17,
        failed_writes=0,
        context_loaded_bytes=9,
        context_loaded_tokens=3,
        cache_hits=0,
        cache_misses=0,
        gc_purged_bytes=17,
    )
    values = {
        "tenant_id": "tenant-1",
        "window_start": DAY,
        "window_end": DAY + timedelta(days=1),
        "provisional": False,
        "policy_version": "graph-artifact-policy@1",
        "catalog_snapshot_checksum": CHECKSUM,
        "usage_watermark": 4,
        "aggregates": (aggregate,),
        "generated_at": DAY + timedelta(days=1),
    }
    first = DailyGraphArtifactCostReport.create(**values)
    second = DailyGraphArtifactCostReport.create(**values)

    assert first == second
    assert aggregate.dedup_savings_basis_points == 5_000
    assert aggregate.cache_hit_ratio_basis_points is None
    assert DailyGraphArtifactCostReport.from_dict(first.to_dict()) == first


def test_alert_identity_is_stable_and_acknowledgement_is_exact() -> None:
    values = {
        "kind": GraphArtifactAlertKind.RUN_QUOTA_PRESSURE,
        "status": GraphArtifactAlertStatus.OPEN,
        "tenant_id": "tenant-1",
        "scope_ref": "run://run-1",
        "policy_version": "graph-artifact-policy@1",
        "window_start": DAY,
        "window_end": DAY + timedelta(days=1),
        "observed_value": 80,
        "limit_value": 100,
        "reason_code": "quota_warning_threshold",
        "created_at": NOW,
        "acknowledged_at": None,
        "acknowledged_by": None,
    }
    opened = GraphArtifactAlert.create(**values)
    acknowledged = GraphArtifactAlert.create(
        **{
            **values,
            "status": GraphArtifactAlertStatus.ACKNOWLEDGED,
            "acknowledged_at": NOW + timedelta(seconds=1),
            "acknowledged_by": "operator-1",
        }
    )

    assert acknowledged.alert_id == opened.alert_id
    assert acknowledged.alert_checksum != opened.alert_checksum
    assert GraphArtifactAlert.from_dict(acknowledged.to_dict()) == acknowledged
    with pytest.raises(GraphArtifactResultError):
        GraphArtifactAlert.create(
            **{
                **values,
                "status": GraphArtifactAlertStatus.ACKNOWLEDGED,
            }
        )
