from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock

import pytest

from framework.harness.artifacts import (
    GraphArtifactDeletionReceipt,
    GraphArtifactGcOperationState,
    GraphArtifactGovernanceRuntime,
    GraphArtifactPhysicalDeleteRequest,
    GraphArtifactQuarantineReceipt,
    GraphArtifactUsageKind,
    GraphArtifactUsageFact,
    GraphArtifactUsageOutcome,
    GraphArtifactUsageReason,
    GraphArtifactAlertStatus,
)
from framework.harness.artifacts.catalog import (
    ArtifactCatalogGcAction,
    ArtifactCatalogRegistrationRequest,
    ArtifactLifecycleAuthorization,
    ArtifactLifecycleAuthorityKind,
    ArtifactLogicalReference,
    ArtifactReferenceKind,
    ArtifactReferenceRetirementReason,
    ArtifactReferenceRetirementRequest,
    ArtifactCatalogReconciliationIssue,
    ArtifactCatalogReconciliationIssueKind,
    ArtifactCatalogReconciliationPlan,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    GraphArtifactRolloutMode,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.storage.artifacts import (
    LocalJsonArtifactCatalog,
    SQLiteGraphResultStore,
)


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
DAY = datetime(2026, 8, 14, tzinfo=UTC)
CHECKSUM = "sha256:" + "a" * 64


@dataclass
class RecordingLifecycle:
    fail_once_after_quarantine: bool = False
    quarantine_calls: int = 0
    purge_calls: int = 0
    quarantines: dict[str, GraphArtifactQuarantineReceipt] = field(
        default_factory=dict
    )
    deletions: dict[str, GraphArtifactDeletionReceipt] = field(
        default_factory=dict
    )
    _lock: Lock = field(default_factory=Lock)

    def quarantine(
        self,
        request: GraphArtifactPhysicalDeleteRequest,
    ) -> GraphArtifactQuarantineReceipt:
        with self._lock:
            self.quarantine_calls += 1
            receipt = self.quarantines.setdefault(
                request.operation_id,
                GraphArtifactQuarantineReceipt.create(
                    operation_id=request.operation_id,
                    ref=request.record.ref,
                    content_checksum=request.record.content_checksum,
                    byte_size=request.record.byte_size,
                    quarantined_at=request.requested_at + timedelta(seconds=1),
                ),
            )
            if self.fail_once_after_quarantine:
                self.fail_once_after_quarantine = False
                raise RuntimeError("injected crash after quarantine")
            return receipt

    def purge(
        self,
        receipt: GraphArtifactQuarantineReceipt,
    ) -> GraphArtifactDeletionReceipt:
        with self._lock:
            self.purge_calls += 1
            return self.deletions.setdefault(
                receipt.operation_id,
                GraphArtifactDeletionReceipt.create(
                    operation_id=receipt.operation_id,
                    quarantine_receipt_checksum=receipt.receipt_checksum,
                    ref=receipt.ref,
                    content_checksum=receipt.content_checksum,
                    byte_size=receipt.byte_size,
                    deleted_at=receipt.quarantined_at + timedelta(seconds=1),
                ),
            )


def test_gc_runtime_applies_full_state_machine_and_records_tombstone(tmp_path) -> None:
    runtime, catalog, store, lifecycle, registered = _runtime_bundle(tmp_path)
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )

    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)
    result = runtime.apply_gc(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
    )

    assert len(result) == 1
    completed = result[0]
    assert completed.state is GraphArtifactGcOperationState.COMPLETED
    assert lifecycle.quarantine_calls == 1
    assert lifecycle.purge_calls == 1
    assert store.get_gc_tombstone(
        tenant_id="tenant-1",
        operation_id=completed.operation_id,
    ) is not None
    with pytest.raises(GraphArtifactResultError) as missing:
        catalog.get(registered.entry.entry_id)
    assert missing.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_CATALOG_NOT_FOUND

    facts = store.list_usage(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
    )
    transitions = tuple(
        fact for fact in facts if fact.kind is GraphArtifactUsageKind.GC_TRANSITION
    )
    assert [fact.reason_code for fact in transitions] == [
        "gc_prepared",
        "gc_catalog_detached",
        "gc_quarantined",
        "gc_purged",
        "gc_completed",
    ]
    purged = next(fact for fact in transitions if fact.reason_code == "gc_purged")
    assert purged.physical_bytes == registered.entry.record.byte_size
    assert purged.object_count == 1


def test_gc_runtime_resumes_after_quarantine_side_effect_crash(tmp_path) -> None:
    lifecycle = RecordingLifecycle(fail_once_after_quarantine=True)
    runtime, _, store, _, registered = _runtime_bundle(
        tmp_path,
        lifecycle=lifecycle,
    )
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )
    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)

    first = runtime.apply_gc(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
    )
    assert first[0].state is GraphArtifactGcOperationState.RETRYABLE_FAILURE
    assert first[0].request is not None
    assert first[0].quarantine is None

    resumed = runtime.resume_gc(tenant_id="tenant-1")

    assert resumed[0].state is GraphArtifactGcOperationState.COMPLETED
    assert len(lifecycle.quarantines) == 1
    assert len(lifecycle.deletions) == 1
    assert store.get_gc_tombstone(
        tenant_id="tenant-1",
        operation_id=resumed[0].operation_id,
    ) is not None


def test_gc_runtime_recovers_catalog_detach_after_ledger_cas_failure(
    tmp_path,
) -> None:
    runtime, catalog, store, lifecycle, registered = _runtime_bundle(tmp_path)
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )
    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)
    original_compare_and_set = store.compare_and_set_gc_operation
    injected = [False]

    def fail_once(operation, *, expected_checksum):
        if (
            not injected[0]
            and operation.state is GraphArtifactGcOperationState.CATALOG_DETACHED
        ):
            injected[0] = True
            raise GraphArtifactResultError(
                GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                details={"field": "injected.catalog_detached"},
            )
        return original_compare_and_set(
            operation,
            expected_checksum=expected_checksum,
        )

    store.compare_and_set_gc_operation = fail_once

    first = runtime.apply_gc(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
    )

    assert first[0].state is GraphArtifactGcOperationState.RETRYABLE_FAILURE
    with pytest.raises(GraphArtifactResultError):
        catalog.get(registered.entry.entry_id)
    assert lifecycle.quarantine_calls == 0

    resumed = runtime.resume_gc(tenant_id="tenant-1")

    assert resumed[0].state is GraphArtifactGcOperationState.COMPLETED
    assert lifecycle.quarantine_calls == 1
    assert lifecycle.purge_calls == 1


def test_concurrent_gc_apply_converges_on_one_completed_operation(tmp_path) -> None:
    runtime, _, store, lifecycle, registered = _runtime_bundle(tmp_path)
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )
    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)

    def apply(_index: int):
        return runtime.apply_gc(
            tenant_id="tenant-1",
            plan_checksum=plan.plan_checksum,
            confirmed=True,
        )[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(apply, (1, 2)))

    assert all(
        operation.state is GraphArtifactGcOperationState.COMPLETED
        for operation in outcomes
    )
    assert outcomes[0] == outcomes[1]
    assert len(lifecycle.quarantines) == 1
    assert len(lifecycle.deletions) == 1
    assert store.get_gc_tombstone(
        tenant_id="tenant-1",
        operation_id=outcomes[0].operation_id,
    ) is not None


def test_gc_runtime_marks_changed_catalog_plan_stale_without_physical_write(
    tmp_path,
) -> None:
    runtime, catalog, _, lifecycle, registered = _runtime_bundle(tmp_path)
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )
    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)
    late_reference = ArtifactLogicalReference.create(
        entry_id=registered.entry.entry_id,
        tenant_id="tenant-1",
        owner_run_id="run-1",
        owner_id="late-replay",
        kind=ArtifactReferenceKind.REPLAY,
        created_at=NOW,
    )
    catalog.add_reference(late_reference)

    result = runtime.apply_gc(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
    )

    assert result[0].state is GraphArtifactGcOperationState.STALE
    assert lifecycle.quarantine_calls == 0
    assert lifecycle.purge_calls == 0
    assert catalog.get(registered.entry.entry_id) == registered.entry


def test_read_only_runtime_plans_without_writes_and_rejects_gc_apply(tmp_path) -> None:
    runtime, _, store, lifecycle, registered = _runtime_bundle(
        tmp_path,
        mode=GraphArtifactRolloutMode.READ_ONLY,
    )

    plan = runtime.plan_gc(tenant_id="tenant-1", observed_at=NOW)

    assert plan.decisions[0].action is not ArtifactCatalogGcAction.DELETE_CANDIDATE
    assert store.usage_watermark(tenant_id="tenant-1") == 0
    assert store.list_gc_operations(
        tenant_id="tenant-1",
        include_completed=True,
    ) == ()
    with pytest.raises(GraphArtifactResultError) as prepare:
        runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)
    assert prepare.value.error_code is (
        GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID
    )
    with pytest.raises(GraphArtifactResultError) as apply:
        runtime.apply_gc(
            tenant_id="tenant-1",
            plan_checksum=plan.plan_checksum,
            confirmed=True,
        )
    assert apply.value.error_code is (
        GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID
    )
    assert lifecycle.quarantine_calls == 0
    assert registered.reference is not None


def test_cost_report_reuses_inputs_and_preserves_open_closed_and_late_revisions(
    tmp_path,
) -> None:
    runtime, _, store, _, _ = _runtime_bundle(tmp_path)

    provisional = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=NOW,
    )
    closed = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=DAY + timedelta(days=1),
    )

    assert provisional.provisional is True
    assert closed.provisional is False
    assert provisional.report_id != closed.report_id
    assert runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=DAY + timedelta(days=1, hours=1),
    ) == closed

    late_fact = GraphArtifactUsageFact.create(
        kind=GraphArtifactUsageKind.MATERIALIZATION,
        outcome=GraphArtifactUsageOutcome.SUCCEEDED,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="late-node",
        artifact_class=ArtifactClass.CONTROL,
        retention_class=RetentionClass.RUN,
        policy_version="graph-artifact-policy@1",
        operation_id="materialization://tenant-1/late-inline",
        logical_bytes=5,
        physical_bytes=0,
        object_count=1,
        reason_code=GraphArtifactUsageReason.INLINE_RESULT.value,
        occurred_at=NOW,
    )
    store.record_usage(late_fact)
    late = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=DAY + timedelta(days=1, hours=2),
    )

    assert late.usage_watermark > closed.usage_watermark
    assert late.report_id != closed.report_id
    assert runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=DAY + timedelta(days=1, hours=3),
    ) == late
    assert store.list_cost_reports(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
    ) == (provisional, closed, late)


def test_alert_delivery_is_idempotent_and_ack_preserves_source_facts(tmp_path) -> None:
    runtime, _, store, _, _ = _runtime_bundle(tmp_path)
    readback_failure = GraphArtifactUsageFact.create(
        kind=GraphArtifactUsageKind.ARTIFACT_READBACK,
        outcome=GraphArtifactUsageOutcome.FAILED,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="source-node",
        artifact_class=ArtifactClass.EVIDENCE,
        retention_class=RetentionClass.EVIDENCE,
        policy_version="graph-artifact-policy@1",
        operation_id="artifact-readback://tenant-1/failure-1",
        reason_code=GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED.value,
        occurred_at=NOW,
    )
    store.record_usage(readback_failure)
    report = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=DAY + timedelta(days=1),
    )
    issue = ArtifactCatalogReconciliationIssue.create(
        kind=ArtifactCatalogReconciliationIssueKind.MISSING_PHYSICAL_OBJECT,
        subject_id="artifact://run-1/missing",
        entry_id="catalog-entry://missing",
    )
    reconciliation = ArtifactCatalogReconciliationPlan.create(
        generated_at=report.generated_at,
        issues=(issue,),
    )

    first = runtime.evaluate_alerts(
        tenant_id="tenant-1",
        report=report,
        reconciliation=reconciliation,
    )
    repeated = runtime.evaluate_alerts(
        tenant_id="tenant-1",
        report=report,
        reconciliation=reconciliation,
    )

    assert repeated == first
    assert len(first) == 2
    acknowledged = runtime.acknowledge_alert(
        tenant_id="tenant-1",
        alert_id=first[0].alert_id,
        expected_checksum=first[0].alert_checksum,
        acknowledged_by="operator-1",
        acknowledged_at=report.generated_at + timedelta(seconds=1),
    )
    assert acknowledged.status is GraphArtifactAlertStatus.ACKNOWLEDGED
    after_ack = runtime.evaluate_alerts(
        tenant_id="tenant-1",
        report=report,
        reconciliation=reconciliation,
    )
    assert acknowledged in after_ack
    assert store.list_usage(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
    ) == (readback_failure,)


def test_cost_report_carries_expiry_backlog_into_completed_gc_tombstone(tmp_path) -> None:
    runtime, _, _, _, registered = _runtime_bundle(tmp_path)
    runtime.retire_reference(
        tenant_id="tenant-1",
        request=_retirement_request(registered.reference),
    )
    plan = runtime.prepare_gc(tenant_id="tenant-1", observed_at=NOW)
    before = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=NOW,
    )
    before_global = next(
        aggregate
        for aggregate in before.aggregates
        if aggregate.dimension.run_id is None
        and aggregate.dimension.artifact_class is None
    )
    assert before_global.expired_bytes == registered.entry.record.byte_size

    runtime.apply_gc(
        tenant_id="tenant-1",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
    )
    after = runtime.generate_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        generated_at=NOW + timedelta(hours=1),
    )
    after_global = next(
        aggregate
        for aggregate in after.aggregates
        if aggregate.dimension.run_id is None
        and aggregate.dimension.artifact_class is None
    )

    assert after.report_id != before.report_id
    assert after_global.logical_bytes == registered.entry.record.byte_size
    assert after_global.unique_physical_bytes == registered.entry.record.byte_size
    assert after_global.expired_bytes == 0
    assert after_global.gc_purged_bytes == registered.entry.record.byte_size


def _runtime_bundle(
    tmp_path,
    *,
    lifecycle: RecordingLifecycle | None = None,
    mode: GraphArtifactRolloutMode = GraphArtifactRolloutMode.ENFORCE,
):
    catalog = LocalJsonArtifactCatalog(tmp_path / "catalog")
    registered = catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            _record(),
            verified_at=NOW - timedelta(days=2),
        )
    )
    store = SQLiteGraphResultStore(
        tmp_path / "graph-results.sqlite3",
        clock=lambda: NOW,
    )
    actual_lifecycle = lifecycle or RecordingLifecycle()
    runtime = GraphArtifactGovernanceRuntime(
        catalog=catalog,
        lifecycle=actual_lifecycle,
        ledger=store,
        config=GraphArtifactPersistenceConfig(mode=mode),
        clock=lambda: NOW,
    )
    return runtime, catalog, store, actual_lifecycle, registered


def _record() -> ArtifactRecord:
    identity = CHECKSUM.removeprefix("sha256:")
    return ArtifactRecord(
        ref=f"artifact://run-1/graph-result-{identity}",
        artifact_id="artifact-1",
        artifact_type=f"graph-result-{identity}",
        content_checksum=CHECKSUM,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="source-node",
        attempt_id="attempt-1",
        producer_revision="producer@1",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW - timedelta(days=1),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW - timedelta(days=3),
    )


def _retirement_request(reference_value) -> ArtifactReferenceRetirementRequest:
    authorization = ArtifactLifecycleAuthorization.create(
        kind=ArtifactLifecycleAuthorityKind.TERMINAL_RUN,
        tenant_id=reference_value.tenant_id,
        owner_run_id=reference_value.owner_run_id,
        owner_id=reference_value.owner_id,
        lifecycle_ref="run-lifecycle://run-1/terminal",
        observed_at=NOW,
        policy_version="graph-artifact-policy@1",
    )
    return ArtifactReferenceRetirementRequest.create(
        reference=reference_value,
        authorization=authorization,
        reason=ArtifactReferenceRetirementReason.RETENTION_EXPIRED,
        requested_at=NOW,
    )
