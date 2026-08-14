from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDecision,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcDetachRequest,
    ArtifactCatalogGcPlan,
    ArtifactCatalogGcReason,
    ArtifactCatalogIdentity,
    ArtifactCatalogReconciliationIssue,
    ArtifactCatalogReconciliationIssueKind,
    ArtifactCatalogReconciliationPlan,
    ArtifactCatalogRegistrationRequest,
    ArtifactCatalogRegistrationResult,
    ArtifactCatalogSnapshot,
    ArtifactLifecycleAuthorization,
    ArtifactLifecycleAuthorityKind,
    ArtifactLogicalReference,
    ArtifactReferenceKind,
    ArtifactReferenceRetirementReason,
    ArtifactReferenceRetirementReceipt,
    ArtifactReferenceRetirementRequest,
    ArtifactVerificationReceipt,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    ResultSensitivity,
    RetentionClass,
)


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64


def _record(
    *,
    tenant_id: str = "tenant-1",
    run_id: str = "run-1",
    artifact_id: str = "artifact-1",
    content_checksum: str = CHECKSUM,
    ref: str | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        ref=ref or f"artifact://{run_id}/{artifact_id}",
        artifact_id=artifact_id,
        artifact_type="node_result",
        content_checksum=content_checksum,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id=tenant_id,
        run_id=run_id,
        graph_id="research-graph",
        node_id="collect-evidence",
        attempt_id="attempt-1",
        producer_revision="research-worker@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW + timedelta(days=30),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW,
    )


def _request(record: ArtifactRecord | None = None) -> ArtifactCatalogRegistrationRequest:
    return ArtifactCatalogRegistrationRequest.from_verified_record(
        record or _record(),
        verified_at=NOW + timedelta(seconds=1),
    )


def test_catalog_contracts_are_immutable_exact_and_round_trip() -> None:
    request = _request()
    entry = ArtifactCatalogEntry.from_verified_record(
        request.record,
        request.verification,
    )
    claim = ArtifactCatalogClaim.for_record(request.record, entry_id=entry.entry_id)
    result = ArtifactCatalogRegistrationResult(
        entry=entry,
        claim=claim,
        reference=request.initial_reference,
        deduplicated=False,
    )

    assert ArtifactCatalogIdentity.from_dict(entry.identity.to_dict()) == entry.identity
    assert ArtifactVerificationReceipt.from_dict(request.verification.to_dict()) == request.verification
    assert ArtifactCatalogEntry.from_dict(entry.to_dict()) == entry
    assert ArtifactCatalogClaim.from_dict(claim.to_dict()) == claim
    assert ArtifactLogicalReference.from_dict(request.initial_reference.to_dict()) == request.initial_reference
    assert ArtifactCatalogRegistrationRequest.from_dict(request.to_dict()) == request
    assert ArtifactCatalogRegistrationResult.from_dict(result.to_dict()) == result
    with pytest.raises(FrozenInstanceError):
        entry.entry_id = "catalog-entry://other"  # type: ignore[misc]
    with pytest.raises(GraphArtifactResultError) as exc_info:
        ArtifactCatalogEntry.from_dict({**entry.to_dict(), "unknown": True})
    assert exc_info.value.error_code is GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID


def test_identity_and_logical_reference_ids_are_content_deterministic() -> None:
    first = _request(_record(run_id="run-1", artifact_id="artifact-a"))
    second = _request(_record(run_id="run-2", artifact_id="artifact-b"))
    first_identity = ArtifactCatalogIdentity.from_record(first.record)
    second_identity = ArtifactCatalogIdentity.from_record(second.record)

    assert first_identity == second_identity
    assert first_identity.entry_id == second_identity.entry_id
    assert first.initial_reference.reference_id != second.initial_reference.reference_id
    assert _request(first.record) == first


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("tenant_id", "tenant-2", GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH),
        ("ref", "artifact://run-1/other", GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED),
        ("content_checksum", "sha256:" + "b" * 64, GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED),
        ("byte_size", 18, GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED),
        ("media_type", "text/plain", GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED),
    ],
)
def test_verification_receipt_mismatch_fails_closed(
    field: str,
    value: object,
    error_code: GraphArtifactResultErrorCode,
) -> None:
    record = _record()
    receipt = ArtifactVerificationReceipt.for_record(
        record,
        verified_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(GraphArtifactResultError) as exc_info:
        ArtifactCatalogEntry.from_verified_record(record, replace(receipt, **{field: value}))

    assert exc_info.value.error_code is error_code


def test_registration_rejects_non_run_or_cross_scope_initial_reference() -> None:
    record = _record()
    identity = ArtifactCatalogIdentity.from_record(record)
    receipt = ArtifactVerificationReceipt.for_record(record, verified_at=NOW + timedelta(seconds=1))
    wrong_reference = ArtifactLogicalReference.create(
        entry_id=identity.entry_id,
        tenant_id=record.tenant_id,
        owner_run_id="run-2",
        owner_id=record.artifact_id,
        kind=ArtifactReferenceKind.RUN,
        created_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(GraphArtifactResultError) as exc_info:
        ArtifactCatalogRegistrationRequest(
            record=record,
            verification=receipt,
            initial_reference=wrong_reference,
        )

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT


def test_registration_rejects_initial_reference_timeline_mismatch() -> None:
    request = _request()
    wrong_reference = replace(
        request.initial_reference,
        created_at=request.initial_reference.created_at + timedelta(seconds=1),
    )

    with pytest.raises(GraphArtifactResultError) as exc_info:
        replace(request, initial_reference=wrong_reference)

    assert exc_info.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT


def test_reference_kind_controls_expiry_contract() -> None:
    entry_id = ArtifactCatalogIdentity.from_record(_record()).entry_id

    with pytest.raises(GraphArtifactResultError):
        ArtifactLogicalReference.create(
            entry_id=entry_id,
            tenant_id="tenant-1",
            owner_run_id="run-1",
            owner_id="cache-1",
            kind=ArtifactReferenceKind.CACHE,
            created_at=NOW,
        )
    with pytest.raises(GraphArtifactResultError):
        ArtifactLogicalReference.create(
            entry_id=entry_id,
            tenant_id="tenant-1",
            owner_run_id="run-1",
            owner_id="report-1",
            kind=ArtifactReferenceKind.REPORT,
            created_at=NOW,
            expires_at=NOW + timedelta(days=1),
        )


def test_gc_and_reconciliation_plans_are_deterministic_exact_contracts() -> None:
    entry = ArtifactCatalogEntry.from_verified_record(
        _request().record,
        _request().verification,
    )
    decision = ArtifactCatalogGcDecision(
        entry_id=entry.entry_id,
        ref=entry.record.ref,
        action=ArtifactCatalogGcAction.KEEP,
        reason=ArtifactCatalogGcReason.RETENTION_ACTIVE,
        active_reference_ids=(),
        byte_size=entry.record.byte_size,
    )
    first = ArtifactCatalogGcPlan.create(generated_at=NOW, decisions=(decision,))
    second = ArtifactCatalogGcPlan.create(generated_at=NOW, decisions=(decision,))
    issue = ArtifactCatalogReconciliationIssue.create(
        kind=ArtifactCatalogReconciliationIssueKind.ORPHAN_ENTRY,
        subject_id=entry.entry_id,
        entry_id=entry.entry_id,
    )
    reconciliation = ArtifactCatalogReconciliationPlan.create(
        generated_at=NOW,
        issues=(issue,),
    )

    assert first == second
    assert ArtifactCatalogGcPlan.from_dict(first.to_dict()) == first
    assert ArtifactCatalogReconciliationPlan.from_dict(reconciliation.to_dict()) == reconciliation
    assert reconciliation.is_clean is False


def test_catalog_snapshot_and_gc_detach_contracts_preserve_exact_evidence() -> None:
    request = _request()
    entry = ArtifactCatalogEntry.from_verified_record(request.record, request.verification)
    claim = ArtifactCatalogClaim.for_record(request.record, entry_id=entry.entry_id)
    logical_reference = request.initial_reference
    snapshot = ArtifactCatalogSnapshot.create(
        captured_at=NOW,
        entries=(entry,),
        claims=(claim,),
        references=(logical_reference,),
    )
    decision = ArtifactCatalogGcDecision(
        entry_id=entry.entry_id,
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
        catalog_snapshot_checksum=snapshot.snapshot_checksum,
    )
    detach_request = ArtifactCatalogGcDetachRequest.create(
        plan_checksum=plan.plan_checksum,
        catalog_snapshot_checksum=snapshot.snapshot_checksum,
        decision=decision,
        requested_at=NOW,
    )
    receipt = ArtifactCatalogGcDetachReceipt.create(
        request_checksum=detach_request.request_checksum,
        entry=entry,
        claims=(claim,),
        references=(logical_reference,),
        detached_at=NOW,
    )

    assert ArtifactCatalogSnapshot.from_dict(snapshot.to_dict()) == snapshot
    assert ArtifactCatalogGcDetachRequest.from_dict(detach_request.to_dict()) == detach_request
    assert ArtifactCatalogGcDetachReceipt.from_dict(receipt.to_dict()) == receipt
    assert decision.decision_checksum is not None
    assert plan.catalog_snapshot_checksum == snapshot.snapshot_checksum


def test_lifecycle_authorization_and_retirement_are_scoped_exact_contracts() -> None:
    logical_reference = _request().initial_reference
    authorization = ArtifactLifecycleAuthorization.create(
        kind=ArtifactLifecycleAuthorityKind.TERMINAL_RUN,
        tenant_id=logical_reference.tenant_id,
        owner_run_id=logical_reference.owner_run_id,
        owner_id=logical_reference.owner_id,
        lifecycle_ref="run-lifecycle://run-1/terminal",
        observed_at=NOW,
        policy_version="graph-artifact-policy@1",
    )
    request = ArtifactReferenceRetirementRequest.create(
        reference=logical_reference,
        authorization=authorization,
        reason=ArtifactReferenceRetirementReason.RETENTION_EXPIRED,
        requested_at=NOW + timedelta(seconds=1),
    )
    receipt = ArtifactReferenceRetirementReceipt.create(
        request_checksum=request.request_checksum,
        reference=logical_reference,
        authorization_id=authorization.authorization_id,
        reason=request.reason,
        retired_at=NOW + timedelta(seconds=1),
    )

    assert ArtifactLifecycleAuthorization.from_dict(authorization.to_dict()) == authorization
    assert ArtifactReferenceRetirementRequest.from_dict(request.to_dict()) == request
    assert ArtifactReferenceRetirementReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(GraphArtifactResultError) as wrong_scope:
        ArtifactReferenceRetirementRequest.create(
            reference=logical_reference,
            authorization=replace(authorization, tenant_id="tenant-2"),
            reason=ArtifactReferenceRetirementReason.RETENTION_EXPIRED,
            requested_at=NOW + timedelta(seconds=1),
        )
    assert wrong_scope.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT
