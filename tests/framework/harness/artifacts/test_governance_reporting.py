from __future__ import annotations

from datetime import UTC, datetime, timedelta

from framework.harness.artifacts import (
    DailyGraphArtifactCostReport,
    GraphArtifactAlertKind,
    GraphArtifactCostAggregate,
    GraphArtifactCostDimension,
    GraphArtifactQuotaScope,
    GraphArtifactQuotaSnapshot,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    GraphArtifactUsageReason,
    build_daily_graph_artifact_cost_report,
    evaluate_graph_artifact_alerts,
)
from framework.harness.artifacts.catalog import (
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDecision,
    ArtifactCatalogGcPlan,
    ArtifactCatalogGcReason,
    ArtifactCatalogReconciliationIssue,
    ArtifactCatalogReconciliationIssueKind,
    ArtifactCatalogReconciliationPlan,
    ArtifactCatalogRegistrationRequest,
)
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultErrorCode,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.storage.artifacts import LocalJsonArtifactCatalog
from framework.shared.json import stable_json_dumps


DAY = datetime(2026, 8, 14, tzinfo=UTC)
NOW = DAY + timedelta(hours=8)
CHECKSUM = "sha256:" + "a" * 64


def test_daily_report_counts_claim_dedup_and_explicit_usage_without_double_count(
    tmp_path,
) -> None:
    catalog = LocalJsonArtifactCatalog(tmp_path / "catalog")
    first = catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            _record(run_id="run-1", node_id="node-1", artifact_id="artifact-1"),
            verified_at=NOW,
        )
    )
    second = catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            _record(run_id="run-2", node_id="node-2", artifact_id="artifact-2"),
            verified_at=NOW,
        )
    )
    assert first.entry == second.entry
    snapshot = catalog.snapshot(captured_at=NOW, tenant_id="tenant-1")
    gc_plan = catalog.plan_gc(now=NOW, tenant_id="tenant-1")
    facts = (
        _usage(
            kind=GraphArtifactUsageKind.MATERIALIZATION,
            outcome=GraphArtifactUsageOutcome.SUCCEEDED,
            operation_id="materialization://tenant-1/inline-1",
            reason=GraphArtifactUsageReason.INLINE_RESULT.value,
            artifact_class=ArtifactClass.CONTROL,
            logical_bytes=5,
            object_count=1,
        ),
        _usage(
            kind=GraphArtifactUsageKind.CONTEXT_LOAD,
            outcome=GraphArtifactUsageOutcome.SUCCEEDED,
            operation_id="context-load://tenant-1/load-1",
            reason=GraphArtifactUsageReason.CONTEXT_LOADED.value,
            loaded_bytes=7,
            loaded_tokens=2,
        ),
        _usage(
            kind=GraphArtifactUsageKind.MATERIALIZATION,
            outcome=GraphArtifactUsageOutcome.FAILED,
            operation_id="materialization://tenant-1/failed-1",
            reason=GraphArtifactResultErrorCode.ARTIFACT_WRITE_FAILED.value,
        ),
        _usage(
            kind=GraphArtifactUsageKind.CACHE_LOOKUP,
            outcome=GraphArtifactUsageOutcome.HIT,
            operation_id="graph-artifact-cache-lookup://cache-a/hit-1",
            reason=GraphArtifactUsageReason.CACHE_HIT.value,
        ),
        _usage(
            kind=GraphArtifactUsageKind.CACHE_LOOKUP,
            outcome=GraphArtifactUsageOutcome.MISS,
            operation_id="graph-artifact-cache-lookup://cache-b/miss-1",
            reason=GraphArtifactUsageReason.CACHE_MISS.value,
        ),
    )

    first_report = build_daily_graph_artifact_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        provisional=False,
        policy_version="graph-artifact-policy@1",
        catalog_snapshot=snapshot,
        usage_watermark=5,
        usage_facts=facts,
        gc_plan=gc_plan,
        completed_operations=(),
        generated_at=DAY + timedelta(days=1),
    )
    repeated = build_daily_graph_artifact_cost_report(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        provisional=False,
        policy_version="graph-artifact-policy@1",
        catalog_snapshot=snapshot,
        usage_watermark=5,
        usage_facts=facts,
        gc_plan=gc_plan,
        completed_operations=(),
        generated_at=DAY + timedelta(days=1),
    )

    assert repeated == first_report
    global_total = _aggregate(first_report, run_id=None, artifact_class=None)
    assert global_total.logical_bytes == 39
    assert global_total.logical_count == 3
    assert global_total.unique_physical_bytes == 17
    assert global_total.unique_physical_count == 1
    assert global_total.failed_writes == 1
    assert global_total.context_loaded_bytes == 7
    assert global_total.context_loaded_tokens == 2
    assert global_total.cache_hits == 1
    assert global_total.cache_misses == 1
    assert global_total.cache_hit_ratio_basis_points == 5_000
    for run_id in ("run-1", "run-2"):
        scoped = _aggregate(
            first_report,
            run_id=run_id,
            artifact_class=ArtifactClass.EVIDENCE,
        )
        assert scoped.logical_bytes == 17
        assert scoped.unique_physical_bytes == 17
        assert scoped.dedup_savings_basis_points == 0
    assert global_total.dedup_savings_basis_points == 5_641


def test_alert_evaluator_covers_thresholds_failures_drift_and_cache_scope() -> None:
    report = _empty_report()
    decision = ArtifactCatalogGcDecision(
        entry_id="catalog-entry://expired",
        tenant_id="tenant-1",
        ref="artifact://run-1/graph-result-expired",
        action=ArtifactCatalogGcAction.DELETE_CANDIDATE,
        reason=ArtifactCatalogGcReason.EXPIRED_UNREFERENCED,
        active_reference_ids=(),
        byte_size=17,
    )
    plan = ArtifactCatalogGcPlan.create(
        generated_at=NOW,
        decisions=(decision,),
        catalog_snapshot_checksum=CHECKSUM,
    )
    quota = (
        GraphArtifactQuotaSnapshot.create(
            scope=GraphArtifactQuotaScope.TENANT,
            tenant_id="tenant-1",
            run_id=None,
            artifact_class=None,
            charged_bytes=80,
            charged_objects=1,
            pending_bytes=0,
            pending_objects=0,
            limit_bytes=100,
            limit_objects=10,
            captured_at=NOW,
        ),
        GraphArtifactQuotaSnapshot.create(
            scope=GraphArtifactQuotaScope.RUN,
            tenant_id="tenant-1",
            run_id="run-1",
            artifact_class=None,
            charged_bytes=1,
            charged_objects=8,
            pending_bytes=0,
            pending_objects=0,
            limit_bytes=100,
            limit_objects=10,
            captured_at=NOW,
        ),
    )
    usage = (
        _usage(
            kind=GraphArtifactUsageKind.ARTIFACT_READBACK,
            outcome=GraphArtifactUsageOutcome.FAILED,
            operation_id="artifact-readback://tenant-1/failure-1",
            reason=GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED.value,
        ),
        *tuple(
            _usage(
                kind=GraphArtifactUsageKind.CACHE_LOOKUP,
                outcome=GraphArtifactUsageOutcome.MISS,
                operation_id=f"graph-artifact-cache-lookup://cache-a/miss-{index}",
                reason=GraphArtifactUsageReason.CACHE_MISS.value,
            )
            for index in range(3)
        ),
    )
    issue = ArtifactCatalogReconciliationIssue.create(
        kind=ArtifactCatalogReconciliationIssueKind.MISSING_PHYSICAL_OBJECT,
        subject_id="artifact://run-1/missing",
        entry_id="catalog-entry://missing",
    )
    reconciliation = ArtifactCatalogReconciliationPlan.create(
        generated_at=NOW,
        issues=(issue,),
    )
    config = GraphArtifactPersistenceConfig(
        quota_alert_threshold_basis_points=8_000,
        gc_backlog_alert_bytes=10,
        cache_stampede_miss_threshold=3,
    )

    alerts = evaluate_graph_artifact_alerts(
        config=config,
        report=report,
        quota_snapshots=quota,
        gc_plan=plan,
        usage_facts=usage,
        reconciliation=reconciliation,
    )
    repeated = evaluate_graph_artifact_alerts(
        config=config,
        report=report,
        quota_snapshots=quota,
        gc_plan=plan,
        usage_facts=usage,
        reconciliation=reconciliation,
    )

    assert alerts == repeated
    assert {alert.kind for alert in alerts} == {
        GraphArtifactAlertKind.TENANT_QUOTA_PRESSURE,
        GraphArtifactAlertKind.RUN_QUOTA_PRESSURE,
        GraphArtifactAlertKind.GC_BACKLOG,
        GraphArtifactAlertKind.READBACK_FAILURE,
        GraphArtifactAlertKind.CACHE_STAMPEDE,
        GraphArtifactAlertKind.CATALOG_DRIFT,
    }
    cache_alert = next(
        alert for alert in alerts if alert.kind is GraphArtifactAlertKind.CACHE_STAMPEDE
    )
    assert cache_alert.observed_value == 3
    assert "cache-a" not in cache_alert.scope_ref
    rendered = stable_json_dumps([alert.to_dict() for alert in alerts])
    assert "artifact://run-1/missing" not in rendered
    assert "C:/" not in rendered


def test_report_without_cache_lookup_has_nullable_ratio() -> None:
    report = _empty_report()
    aggregate = report.aggregates[0]
    assert aggregate.cache_hits == 0
    assert aggregate.cache_misses == 0
    assert aggregate.cache_hit_ratio_basis_points is None


def _record(*, run_id: str, node_id: str, artifact_id: str) -> ArtifactRecord:
    identity = CHECKSUM.removeprefix("sha256:")
    return ArtifactRecord(
        ref=f"artifact://{run_id}/graph-result-{artifact_id}",
        artifact_id=artifact_id,
        artifact_type=f"graph-result-{artifact_id}",
        content_checksum=CHECKSUM,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id="tenant-1",
        run_id=run_id,
        graph_id="graph-1",
        node_id=node_id,
        attempt_id="attempt-1",
        producer_revision="producer@1",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW + timedelta(days=1),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW,
    )


def _usage(
    *,
    kind: GraphArtifactUsageKind,
    outcome: GraphArtifactUsageOutcome,
    operation_id: str,
    reason: str,
    artifact_class: ArtifactClass = ArtifactClass.EVIDENCE,
    logical_bytes: int = 0,
    loaded_bytes: int = 0,
    loaded_tokens: int = 0,
    object_count: int = 0,
) -> GraphArtifactUsageFact:
    return GraphArtifactUsageFact.create(
        kind=kind,
        outcome=outcome,
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="graph-1",
        node_id="node-1",
        artifact_class=artifact_class,
        retention_class=RetentionClass.EVIDENCE,
        policy_version="graph-artifact-policy@1",
        operation_id=operation_id,
        logical_bytes=logical_bytes,
        loaded_bytes=loaded_bytes,
        loaded_tokens=loaded_tokens,
        object_count=object_count,
        reason_code=reason,
        occurred_at=NOW,
    )


def _aggregate(
    report: DailyGraphArtifactCostReport,
    *,
    run_id: str | None,
    artifact_class: ArtifactClass | None,
) -> GraphArtifactCostAggregate:
    return next(
        aggregate
        for aggregate in report.aggregates
        if aggregate.dimension.run_id == run_id
        and aggregate.dimension.graph_id is None
        and aggregate.dimension.node_id is None
        and aggregate.dimension.artifact_class is artifact_class
    )


def _empty_report() -> DailyGraphArtifactCostReport:
    dimension = GraphArtifactCostDimension(
        tenant_id="tenant-1",
        run_id=None,
        graph_id=None,
        node_id=None,
        artifact_class=None,
        policy_version="graph-artifact-policy@1",
    )
    aggregate = GraphArtifactCostAggregate.create(
        dimension=dimension,
        logical_bytes=0,
        logical_count=0,
        unique_physical_bytes=0,
        unique_physical_count=0,
        expired_bytes=0,
        failed_writes=0,
        context_loaded_bytes=0,
        context_loaded_tokens=0,
        cache_hits=0,
        cache_misses=0,
        gc_purged_bytes=0,
    )
    return DailyGraphArtifactCostReport.create(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        provisional=False,
        policy_version="graph-artifact-policy@1",
        catalog_snapshot_checksum=CHECKSUM,
        usage_watermark=4,
        aggregates=(aggregate,),
        generated_at=DAY + timedelta(days=1),
    )
