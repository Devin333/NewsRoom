from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence
from urllib.parse import urlsplit

from framework.events.canonical import checksum_for
from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcAction,
    ArtifactCatalogGcPlan,
    ArtifactCatalogReconciliationPlan,
    ArtifactCatalogSnapshot,
)
from framework.harness.artifacts.governance import (
    DailyGraphArtifactCostReport,
    GraphArtifactAlert,
    GraphArtifactAlertKind,
    GraphArtifactAlertReason,
    GraphArtifactAlertStatus,
    GraphArtifactCostAggregate,
    GraphArtifactCostDimension,
    GraphArtifactGcOperation,
    GraphArtifactGcOperationState,
    GraphArtifactQuotaScope,
    GraphArtifactQuotaSnapshot,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    GraphArtifactUsageReason,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import ArtifactClass, ArtifactRecord
from framework.harness.runtime.result_policy import GraphArtifactPersistenceConfig


@dataclass(slots=True)
class _CostAccumulator:
    logical_bytes: int = 0
    logical_count: int = 0
    entry_sizes: dict[str, int] = field(default_factory=dict)
    expired_entry_sizes: dict[str, int] = field(default_factory=dict)
    failed_writes: int = 0
    context_loaded_bytes: int = 0
    context_loaded_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    gc_purged_bytes: int = 0


_DimensionKey = tuple[
    str | None,
    str | None,
    str | None,
    ArtifactClass | None,
    str,
]


def build_daily_graph_artifact_cost_report(
    *,
    tenant_id: str,
    window_start: datetime,
    window_end: datetime,
    provisional: bool,
    policy_version: str,
    catalog_snapshot: ArtifactCatalogSnapshot,
    usage_watermark: int,
    usage_facts: Sequence[GraphArtifactUsageFact],
    gc_plan: ArtifactCatalogGcPlan,
    completed_operations: Sequence[GraphArtifactGcOperation],
    generated_at: datetime,
) -> DailyGraphArtifactCostReport:
    accumulators: dict[_DimensionKey, _CostAccumulator] = {}
    accumulators[(None, None, None, None, policy_version)] = _CostAccumulator()
    entries: dict[str, ArtifactCatalogEntry] = {
        entry.entry_id: entry for entry in catalog_snapshot.entries
    }
    claims: dict[str, ArtifactCatalogClaim] = {
        claim.claim_id: claim for claim in catalog_snapshot.claims
    }
    claim_policy: dict[str, str] = {
        claim.claim_id: policy_version for claim in catalog_snapshot.claims
    }

    for operation in completed_operations:
        if (
            not isinstance(operation, GraphArtifactGcOperation)
            or operation.intent.tenant_id != tenant_id
            or operation.state is not GraphArtifactGcOperationState.COMPLETED
            or not window_start <= operation.updated_at < window_end
        ):
            continue
        entries.setdefault(operation.intent.entry.entry_id, operation.intent.entry)
        for claim in operation.intent.claims:
            claims.setdefault(claim.claim_id, claim)
            claim_policy.setdefault(claim.claim_id, operation.intent.policy_version)

    reachable_entries: set[str] = set()
    for claim in sorted(claims.values(), key=lambda item: item.claim_id):
        entry = entries.get(claim.entry_id)
        if entry is None:
            raise result_error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                field="cost_report.claim_entry",
            )
        reachable_entries.add(entry.entry_id)
        _add_claim(
            accumulators,
            claim=claim,
            entry=entry,
            policy_version=claim_policy[claim.claim_id],
        )
    if set(entries).difference(reachable_entries):
        raise result_error(
            GraphArtifactResultErrorCode.COST_REPORT_FAILED,
            field="cost_report.unclaimed_entry",
        )

    facts = tuple(usage_facts)
    if any(
        not isinstance(fact, GraphArtifactUsageFact)
        or fact.tenant_id != tenant_id
        or not window_start <= fact.occurred_at < window_end
        for fact in facts
    ):
        raise result_error(
            GraphArtifactResultErrorCode.COST_REPORT_FAILED,
            field="cost_report.usage",
        )
    for fact in facts:
        for key in _rollup_keys(
            run_id=fact.run_id,
            graph_id=fact.graph_id,
            node_id=fact.node_id,
            artifact_class=fact.artifact_class,
            policy_version=fact.policy_version,
        ):
            accumulator = accumulators.setdefault(key, _CostAccumulator())
            if (
                fact.kind is GraphArtifactUsageKind.MATERIALIZATION
                and fact.outcome is GraphArtifactUsageOutcome.SUCCEEDED
                and fact.reason_code
                in {
                    GraphArtifactUsageReason.INLINE_RESULT.value,
                    GraphArtifactUsageReason.CACHE_RESULT.value,
                }
            ):
                accumulator.logical_bytes += fact.logical_bytes
                accumulator.logical_count += fact.object_count
            if (
                fact.kind is GraphArtifactUsageKind.MATERIALIZATION
                and fact.outcome is GraphArtifactUsageOutcome.FAILED
            ):
                accumulator.failed_writes += 1
            if (
                fact.kind is GraphArtifactUsageKind.CONTEXT_LOAD
                and fact.outcome is GraphArtifactUsageOutcome.SUCCEEDED
            ):
                accumulator.context_loaded_bytes += fact.loaded_bytes
                accumulator.context_loaded_tokens += fact.loaded_tokens
            if fact.kind is GraphArtifactUsageKind.CACHE_LOOKUP:
                if fact.outcome is GraphArtifactUsageOutcome.HIT:
                    accumulator.cache_hits += 1
                elif fact.outcome is GraphArtifactUsageOutcome.MISS:
                    accumulator.cache_misses += 1
            if (
                fact.kind is GraphArtifactUsageKind.GC_TRANSITION
                and fact.outcome is GraphArtifactUsageOutcome.SUCCEEDED
                and fact.reason_code == GraphArtifactUsageReason.GC_PURGED.value
            ):
                accumulator.gc_purged_bytes += fact.physical_bytes

    snapshot_entries = {
        entry.entry_id: entry for entry in catalog_snapshot.entries
    }
    snapshot_claims_by_entry: dict[str, tuple[ArtifactCatalogClaim, ...]] = {}
    for entry_id in snapshot_entries:
        snapshot_claims_by_entry[entry_id] = tuple(
            claim
            for claim in catalog_snapshot.claims
            if claim.entry_id == entry_id
        )
    if gc_plan.catalog_snapshot_checksum != catalog_snapshot.snapshot_checksum:
        raise result_error(
            GraphArtifactResultErrorCode.COST_REPORT_FAILED,
            field="cost_report.gc_plan",
        )
    for decision in gc_plan.decisions:
        if decision.action is not ArtifactCatalogGcAction.DELETE_CANDIDATE:
            continue
        entry = snapshot_entries.get(decision.entry_id)
        if entry is None:
            raise result_error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                field="cost_report.gc_entry",
            )
        decision_claims = snapshot_claims_by_entry[entry.entry_id]
        records: Iterable[ArtifactRecord] = (
            (claim.record for claim in decision_claims)
            if decision_claims
            else (entry.record,)
        )
        seen_keys: set[_DimensionKey] = set()
        for record in records:
            seen_keys.update(
                _rollup_keys(
                    run_id=record.run_id,
                    graph_id=record.graph_id,
                    node_id=record.node_id,
                    artifact_class=record.artifact_class,
                    policy_version=policy_version,
                )
            )
        for key in seen_keys:
            accumulators.setdefault(key, _CostAccumulator()).expired_entry_sizes[
                entry.entry_id
            ] = entry.record.byte_size

    aggregates = tuple(
        GraphArtifactCostAggregate.create(
            dimension=GraphArtifactCostDimension(
                tenant_id=tenant_id,
                run_id=key[0],
                graph_id=key[1],
                node_id=key[2],
                artifact_class=key[3],
                policy_version=key[4],
            ),
            logical_bytes=value.logical_bytes,
            logical_count=value.logical_count,
            unique_physical_bytes=sum(value.entry_sizes.values()),
            unique_physical_count=len(value.entry_sizes),
            expired_bytes=sum(value.expired_entry_sizes.values()),
            failed_writes=value.failed_writes,
            context_loaded_bytes=value.context_loaded_bytes,
            context_loaded_tokens=value.context_loaded_tokens,
            cache_hits=value.cache_hits,
            cache_misses=value.cache_misses,
            gc_purged_bytes=value.gc_purged_bytes,
        )
        for key, value in sorted(
            accumulators.items(),
            key=lambda item: _dimension_sort_key(tenant_id, item[0]),
        )
    )
    return DailyGraphArtifactCostReport.create(
        tenant_id=tenant_id,
        window_start=window_start,
        window_end=window_end,
        provisional=provisional,
        policy_version=policy_version,
        catalog_snapshot_checksum=catalog_snapshot.snapshot_checksum,
        usage_watermark=usage_watermark,
        aggregates=aggregates,
        generated_at=generated_at,
    )


def evaluate_graph_artifact_alerts(
    *,
    config: GraphArtifactPersistenceConfig,
    report: DailyGraphArtifactCostReport,
    quota_snapshots: Sequence[GraphArtifactQuotaSnapshot] = (),
    gc_plan: ArtifactCatalogGcPlan | None = None,
    usage_facts: Sequence[GraphArtifactUsageFact] = (),
    reconciliation: ArtifactCatalogReconciliationPlan | None = None,
) -> tuple[GraphArtifactAlert, ...]:
    if not isinstance(config, GraphArtifactPersistenceConfig) or not isinstance(
        report,
        DailyGraphArtifactCostReport,
    ):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="alert.inputs",
        )
    alerts: dict[str, GraphArtifactAlert] = {}

    for snapshot in quota_snapshots:
        if (
            not isinstance(snapshot, GraphArtifactQuotaSnapshot)
            or snapshot.tenant_id != report.tenant_id
            or snapshot.scope is GraphArtifactQuotaScope.ARTIFACT_CLASS
        ):
            continue
        byte_usage = snapshot.charged_bytes + snapshot.pending_bytes
        object_usage = snapshot.charged_objects + snapshot.pending_objects
        byte_alert = (
            byte_usage * 10_000
            >= snapshot.limit_bytes * config.quota_alert_threshold_basis_points
        )
        object_alert = (
            object_usage * 10_000
            >= snapshot.limit_objects * config.quota_alert_threshold_basis_points
        )
        if not byte_alert and not object_alert:
            continue
        use_bytes = (
            byte_usage * snapshot.limit_objects
            >= object_usage * snapshot.limit_bytes
        )
        if snapshot.scope is GraphArtifactQuotaScope.RUN:
            kind = GraphArtifactAlertKind.RUN_QUOTA_PRESSURE
            scope_ref = f"graph-artifact-quota://{report.tenant_id}/run/{snapshot.run_id}"
        else:
            kind = GraphArtifactAlertKind.TENANT_QUOTA_PRESSURE
            scope_ref = f"graph-artifact-quota://{report.tenant_id}/tenant"
        _add_alert(
            alerts,
            kind=kind,
            report=report,
            scope_ref=scope_ref,
            observed_value=(byte_usage if use_bytes else object_usage),
            limit_value=(snapshot.limit_bytes if use_bytes else snapshot.limit_objects),
            reason=GraphArtifactAlertReason.QUOTA_WARNING_THRESHOLD,
        )

    if gc_plan is not None:
        backlog = sum(
            decision.byte_size
            for decision in gc_plan.decisions
            if decision.action is ArtifactCatalogGcAction.DELETE_CANDIDATE
            and decision.tenant_id == report.tenant_id
        )
        if backlog > config.gc_backlog_alert_bytes:
            _add_alert(
                alerts,
                kind=GraphArtifactAlertKind.GC_BACKLOG,
                report=report,
                scope_ref=f"graph-artifact-gc-backlog://{report.tenant_id}",
                observed_value=backlog,
                limit_value=config.gc_backlog_alert_bytes,
                reason=GraphArtifactAlertReason.GC_BACKLOG_THRESHOLD,
            )

    cache_misses: dict[str, int] = {}
    for fact in usage_facts:
        if not isinstance(fact, GraphArtifactUsageFact) or fact.tenant_id != report.tenant_id:
            continue
        if (
            fact.kind
            in {
                GraphArtifactUsageKind.ARTIFACT_READBACK,
                GraphArtifactUsageKind.CACHE_READBACK,
            }
            and fact.outcome is GraphArtifactUsageOutcome.FAILED
        ):
            _add_alert(
                alerts,
                kind=GraphArtifactAlertKind.READBACK_FAILURE,
                report=report,
                scope_ref=fact.fact_id,
                observed_value=1,
                limit_value=0,
                reason=GraphArtifactAlertReason.READBACK_FAILURE,
            )
        if (
            fact.kind is GraphArtifactUsageKind.CACHE_LOOKUP
            and fact.outcome is GraphArtifactUsageOutcome.MISS
        ):
            cache_scope = _cache_lookup_scope(fact.operation_id)
            cache_misses[cache_scope] = cache_misses.get(cache_scope, 0) + 1
    for cache_scope, misses in sorted(cache_misses.items()):
        if misses < config.cache_stampede_miss_threshold:
            continue
        scope_digest = checksum_for(
            {"tenant_id": report.tenant_id, "cache_scope": cache_scope}
        ).removeprefix("sha256:")
        _add_alert(
            alerts,
            kind=GraphArtifactAlertKind.CACHE_STAMPEDE,
            report=report,
            scope_ref=f"graph-artifact-cache-scope://{scope_digest}",
            observed_value=misses,
            limit_value=config.cache_stampede_miss_threshold,
            reason=GraphArtifactAlertReason.CACHE_STAMPEDE,
        )

    if reconciliation is not None:
        for issue in reconciliation.issues:
            _add_alert(
                alerts,
                kind=GraphArtifactAlertKind.CATALOG_DRIFT,
                report=report,
                scope_ref=issue.issue_id,
                observed_value=1,
                limit_value=0,
                reason=GraphArtifactAlertReason.CATALOG_DRIFT,
            )
    return tuple(sorted(alerts.values(), key=lambda alert: alert.alert_id))


def _add_claim(
    accumulators: dict[_DimensionKey, _CostAccumulator],
    *,
    claim: ArtifactCatalogClaim,
    entry: ArtifactCatalogEntry,
    policy_version: str,
) -> None:
    for key in _rollup_keys(
        run_id=claim.record.run_id,
        graph_id=claim.record.graph_id,
        node_id=claim.record.node_id,
        artifact_class=claim.record.artifact_class,
        policy_version=policy_version,
    ):
        accumulator = accumulators.setdefault(key, _CostAccumulator())
        accumulator.logical_bytes += claim.record.byte_size
        accumulator.logical_count += 1
        accumulator.entry_sizes.setdefault(entry.entry_id, entry.record.byte_size)


def _rollup_keys(
    *,
    run_id: str | None,
    graph_id: str | None,
    node_id: str | None,
    artifact_class: ArtifactClass | None,
    policy_version: str,
) -> tuple[_DimensionKey, ...]:
    keys: set[_DimensionKey] = {(None, None, None, None, policy_version)}
    if artifact_class is not None:
        keys.add((None, None, None, artifact_class, policy_version))
    if run_id is not None:
        keys.add((run_id, None, None, None, policy_version))
        if artifact_class is not None:
            keys.add((run_id, None, None, artifact_class, policy_version))
    if run_id is not None and graph_id is not None:
        keys.add((run_id, graph_id, None, None, policy_version))
        if artifact_class is not None:
            keys.add((run_id, graph_id, None, artifact_class, policy_version))
    if run_id is not None and graph_id is not None and node_id is not None:
        keys.add((run_id, graph_id, node_id, None, policy_version))
        if artifact_class is not None:
            keys.add((run_id, graph_id, node_id, artifact_class, policy_version))
    return tuple(sorted(keys, key=lambda item: _dimension_sort_key("", item)))


def _dimension_sort_key(tenant_id: str, key: _DimensionKey) -> tuple[str, ...]:
    return GraphArtifactCostDimension(
        tenant_id=tenant_id or "tenant",
        run_id=key[0],
        graph_id=key[1],
        node_id=key[2],
        artifact_class=key[3],
        policy_version=key[4],
    ).sort_key()


def _add_alert(
    alerts: dict[str, GraphArtifactAlert],
    *,
    kind: GraphArtifactAlertKind,
    report: DailyGraphArtifactCostReport,
    scope_ref: str,
    observed_value: int,
    limit_value: int,
    reason: GraphArtifactAlertReason,
) -> None:
    alert = GraphArtifactAlert.create(
        kind=kind,
        status=GraphArtifactAlertStatus.OPEN,
        tenant_id=report.tenant_id,
        scope_ref=scope_ref,
        policy_version=report.policy_version,
        window_start=report.window_start,
        window_end=report.window_end,
        observed_value=observed_value,
        limit_value=limit_value,
        reason_code=reason.value,
        created_at=report.generated_at,
        acknowledged_at=None,
        acknowledged_by=None,
    )
    existing = alerts.get(alert.alert_id)
    if existing is not None and existing != alert:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
            field="alert.identity",
        )
    alerts[alert.alert_id] = alert


def _cache_lookup_scope(operation_id: str) -> str:
    parsed = urlsplit(operation_id)
    if parsed.scheme == "graph-artifact-cache-lookup" and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return operation_id


__all__ = [
    "build_daily_graph_artifact_cost_report",
    "evaluate_graph_artifact_alerts",
]
