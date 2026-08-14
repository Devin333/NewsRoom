from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from framework.harness.artifacts.catalog import (
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcDetachRequest,
    ArtifactCatalogGcPlan,
    ArtifactCatalogReconciliationPlan,
    ArtifactCatalogSnapshot,
    ArtifactReferenceRetirementReceipt,
    ArtifactReferenceRetirementRequest,
)
from framework.harness.artifacts.governance import (
    GraphArtifactGcOperation,
    GraphArtifactGcOperationIntent,
    GraphArtifactGcOperationState,
    GraphArtifactGovernanceLedgerPort,
    GraphArtifactPhysicalDeleteRequest,
    GraphArtifactPhysicalLifecyclePort,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    GraphArtifactUsageReason,
    DailyGraphArtifactCostReport,
    GraphArtifactAlert,
    GraphArtifactAlertStatus,
)
from framework.harness.artifacts.ports import ArtifactCatalogPort
from framework.harness.artifacts.reporting import (
    build_daily_graph_artifact_cost_report,
    evaluate_graph_artifact_alerts,
)
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    identifier,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_policy import (
    GraphArtifactPersistenceConfig,
    GraphArtifactRolloutMode,
)
from framework.shared.time import utc_now


DEFAULT_MAX_GC_OPERATIONS = 100
MAX_GC_OPERATIONS = 10_000
_MAX_COHERENT_SNAPSHOT_ATTEMPTS = 3
_MAX_OPERATION_TRANSITIONS = 8
_TERMINAL_GC_STATES = frozenset(
    {
        GraphArtifactGcOperationState.COMPLETED,
        GraphArtifactGcOperationState.STALE,
    }
)


class GraphArtifactGovernanceRuntime:
    """Deterministic Harness controller for Graph artifact lifecycle changes."""

    def __init__(
        self,
        *,
        catalog: ArtifactCatalogPort,
        lifecycle: GraphArtifactPhysicalLifecyclePort,
        ledger: GraphArtifactGovernanceLedgerPort,
        config: GraphArtifactPersistenceConfig,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(catalog, ArtifactCatalogPort):
            raise TypeError("catalog must implement ArtifactCatalogPort")
        if not isinstance(lifecycle, GraphArtifactPhysicalLifecyclePort):
            raise TypeError(
                "lifecycle must implement GraphArtifactPhysicalLifecyclePort"
            )
        if not isinstance(ledger, GraphArtifactGovernanceLedgerPort):
            raise TypeError("ledger must implement GraphArtifactGovernanceLedgerPort")
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise TypeError("config must be GraphArtifactPersistenceConfig")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._catalog = catalog
        self._lifecycle = lifecycle
        self._ledger = ledger
        self._config = config
        self._clock = clock

    @property
    def config(self) -> GraphArtifactPersistenceConfig:
        return self._config

    def plan_gc(
        self,
        *,
        tenant_id: str,
        observed_at: datetime | None = None,
    ) -> ArtifactCatalogGcPlan:
        tenant = identifier(tenant_id, "governance.tenant_id")
        now = self._time(observed_at)
        plan, _ = self._coherent_plan_snapshot(tenant_id=tenant, observed_at=now)
        return plan

    def prepare_gc(
        self,
        *,
        tenant_id: str,
        observed_at: datetime | None = None,
    ) -> ArtifactCatalogGcPlan:
        self._require_enforce("prepare_gc")
        tenant = identifier(tenant_id, "governance.tenant_id")
        now = self._time(observed_at)
        plan, snapshot = self._coherent_plan_snapshot(
            tenant_id=tenant,
            observed_at=now,
        )
        stored_plan = self._ledger.put_gc_plan(tenant_id=tenant, plan=plan)
        if stored_plan != plan:
            raise self._ledger_error("gc_plan")

        entries = {entry.entry_id: entry for entry in snapshot.entries}
        claims = {claim.claim_id: claim for claim in snapshot.claims}
        references = {
            logical.reference_id: logical for logical in snapshot.references
        }
        active = self._ledger.list_gc_operations(
            tenant_id=tenant,
            include_completed=False,
        )
        active_by_entry = {
            operation.intent.entry.entry_id: operation
            for operation in active
            if operation.state not in _TERMINAL_GC_STATES
        }
        for decision in plan.decisions:
            if decision.action is not ArtifactCatalogGcAction.DELETE_CANDIDATE:
                continue
            entry = entries.get(decision.entry_id)
            evidence_claims = tuple(
                claims[claim_id]
                for claim_id in decision.claim_ids
                if claim_id in claims
            )
            evidence_references = tuple(
                references[reference_id]
                for reference_id in decision.reference_ids
                if reference_id in references
            )
            if (
                entry is None
                or len(evidence_claims) != len(decision.claim_ids)
                or len(evidence_references) != len(decision.reference_ids)
            ):
                raise result_error(
                    GraphArtifactResultErrorCode.GC_PLAN_STALE,
                    field="governance.prepare.evidence",
                )
            intent = GraphArtifactGcOperationIntent.create(
                tenant_id=tenant,
                plan_checksum=plan.plan_checksum,
                catalog_snapshot_checksum=plan.catalog_snapshot_checksum,
                policy_version=plan.policy_version,
                decision=decision,
                entry=entry,
                claims=evidence_claims,
                references=evidence_references,
                prepared_at=plan.generated_at,
            )
            other = active_by_entry.get(entry.entry_id)
            if other is not None and other.operation_id != intent.operation_id:
                raise result_error(
                    GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                    field="governance.prepare.active_entry",
                )
            prepared = GraphArtifactGcOperation.create(
                operation_id=intent.operation_id,
                state=GraphArtifactGcOperationState.PREPARED,
                intent=intent,
                request=None,
                quarantine=None,
                deletion=None,
                error_code=None,
                updated_at=plan.generated_at,
            )
            existing = self._ledger.get_gc_operation(
                tenant_id=tenant,
                operation_id=intent.operation_id,
            )
            stored = (
                self._ledger.put_gc_operation(prepared)
                if existing is None
                else existing
            )
            if stored.intent != intent:
                raise result_error(
                    GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                    field="governance.prepare.operation",
                )
            self._record_transition_usage(stored)
        return plan

    def apply_gc(
        self,
        *,
        tenant_id: str,
        plan_checksum: str,
        confirmed: bool,
        max_operations: int = DEFAULT_MAX_GC_OPERATIONS,
    ) -> tuple[GraphArtifactGcOperation, ...]:
        self._require_enforce("apply_gc")
        if confirmed is not True:
            raise result_error(
                GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID,
                field="governance.apply.confirmed",
            )
        tenant = identifier(tenant_id, "governance.tenant_id")
        normalized_plan = reference(
            plan_checksum,
            "governance.plan_checksum",
        )
        limit = _operation_limit(max_operations)
        plan = self._ledger.get_gc_plan(
            tenant_id=tenant,
            plan_checksum=normalized_plan,
        )
        if plan is None:
            raise result_error(
                GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                field="governance.plan_checksum",
            )
        operations = {
            operation.intent.decision.decision_checksum: operation
            for operation in self._ledger.list_gc_operations(
                tenant_id=tenant,
                include_completed=True,
            )
            if operation.intent.plan_checksum == plan.plan_checksum
        }
        selected: list[GraphArtifactGcOperation] = []
        for decision in plan.decisions:
            if decision.action is not ArtifactCatalogGcAction.DELETE_CANDIDATE:
                continue
            operation = operations.get(decision.decision_checksum)
            if operation is None:
                raise result_error(
                    GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                    field="governance.gc_operation",
                )
            if len(selected) >= limit:
                break
            selected.append(self._advance_operation(operation))
        return tuple(selected)

    def resume_gc(
        self,
        *,
        tenant_id: str,
        max_operations: int = DEFAULT_MAX_GC_OPERATIONS,
    ) -> tuple[GraphArtifactGcOperation, ...]:
        self._require_enforce("resume_gc")
        tenant = identifier(tenant_id, "governance.tenant_id")
        limit = _operation_limit(max_operations)
        pending = tuple(
            operation
            for operation in self._ledger.list_gc_operations(
                tenant_id=tenant,
                include_completed=False,
            )
            if operation.state is not GraphArtifactGcOperationState.STALE
        )
        return tuple(
            self._advance_operation(operation)
            for operation in pending[:limit]
        )

    def retire_reference(
        self,
        *,
        tenant_id: str,
        request: ArtifactReferenceRetirementRequest,
    ) -> ArtifactReferenceRetirementReceipt:
        self._require_enforce("retire_reference")
        tenant = identifier(tenant_id, "governance.tenant_id")
        if (
            not isinstance(request, ArtifactReferenceRetirementRequest)
            or request.reference.tenant_id != tenant
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="governance.retirement",
            )
        self._config.ensure_readable_policy_version(
            request.authorization.policy_version
        )
        return self._catalog.retire_reference(request)

    def generate_cost_report(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        generated_at: datetime | None = None,
    ) -> DailyGraphArtifactCostReport:
        tenant = identifier(tenant_id, "governance.tenant_id")
        start = aware_datetime(window_start, "governance.window_start")
        end = start + timedelta(days=1)
        now = self._time(generated_at)
        if now < start:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="governance.generated_at",
            )
        provisional = now < end
        plan, snapshot = self._coherent_plan_snapshot(
            tenant_id=tenant,
            observed_at=now,
        )
        watermark = self._ledger.usage_watermark(tenant_id=tenant)
        existing_reports = self._ledger.list_cost_reports(
            tenant_id=tenant,
            window_start=start,
            window_end=end,
        )
        for existing in existing_reports:
            if (
                existing.provisional is provisional
                and existing.policy_version == self._config.policy_version
                and existing.catalog_snapshot_checksum == snapshot.snapshot_checksum
                and existing.usage_watermark == watermark
            ):
                return existing
        usage = self._ledger.list_usage(
            tenant_id=tenant,
            window_start=start,
            window_end=end,
            watermark=watermark,
        )
        report = build_daily_graph_artifact_cost_report(
            tenant_id=tenant,
            window_start=start,
            window_end=end,
            provisional=provisional,
            policy_version=self._config.policy_version,
            catalog_snapshot=snapshot,
            usage_watermark=watermark,
            usage_facts=usage,
            gc_plan=plan,
            completed_operations=self._ledger.list_gc_operations(
                tenant_id=tenant,
                include_completed=True,
            ),
            generated_at=now,
        )
        if self._config.mode is GraphArtifactRolloutMode.LEGACY:
            return report
        stored = self._ledger.put_cost_report(report)
        if stored != report:
            raise result_error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                field="governance.cost_report",
            )
        return stored

    def evaluate_alerts(
        self,
        *,
        tenant_id: str,
        report: DailyGraphArtifactCostReport,
        gc_plan: ArtifactCatalogGcPlan | None = None,
        reconciliation: ArtifactCatalogReconciliationPlan | None = None,
    ) -> tuple[GraphArtifactAlert, ...]:
        tenant = identifier(tenant_id, "governance.tenant_id")
        if not isinstance(report, DailyGraphArtifactCostReport) or report.tenant_id != tenant:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="governance.alert.report",
            )
        usage = self._ledger.list_usage(
            tenant_id=tenant,
            window_start=report.window_start,
            window_end=report.window_end,
            watermark=report.usage_watermark,
        )
        candidates = evaluate_graph_artifact_alerts(
            config=self._config,
            report=report,
            quota_snapshots=self._ledger.quota_snapshots(
                tenant_id=tenant,
                captured_at=report.generated_at,
            ),
            gc_plan=gc_plan,
            usage_facts=usage,
            reconciliation=reconciliation,
        )
        if self._config.mode is GraphArtifactRolloutMode.LEGACY:
            return candidates
        delivered: list[GraphArtifactAlert] = []
        for candidate in candidates:
            existing = self._ledger.get_alert(
                tenant_id=tenant,
                alert_id=candidate.alert_id,
            )
            delivered.append(
                self._ledger.put_alert(candidate)
                if existing is None
                else existing
            )
        return tuple(sorted(delivered, key=lambda alert: alert.alert_id))

    def list_alerts(
        self,
        *,
        tenant_id: str,
        status: GraphArtifactAlertStatus | None = None,
    ) -> tuple[GraphArtifactAlert, ...]:
        return self._ledger.list_alerts(
            tenant_id=identifier(tenant_id, "governance.tenant_id"),
            status=status,
        )

    def acknowledge_alert(
        self,
        *,
        tenant_id: str,
        alert_id: str,
        expected_checksum: str,
        acknowledged_by: str,
        acknowledged_at: datetime | None = None,
    ) -> GraphArtifactAlert:
        return self._ledger.acknowledge_alert(
            tenant_id=identifier(tenant_id, "governance.tenant_id"),
            alert_id=reference(alert_id, "governance.alert_id"),
            expected_checksum=expected_checksum,
            acknowledged_at=self._time(acknowledged_at),
            acknowledged_by=identifier(
                acknowledged_by,
                "governance.acknowledged_by",
            ),
        )

    def _coherent_plan_snapshot(
        self,
        *,
        tenant_id: str,
        observed_at: datetime,
    ) -> tuple[ArtifactCatalogGcPlan, ArtifactCatalogSnapshot]:
        for _ in range(_MAX_COHERENT_SNAPSHOT_ATTEMPTS):
            raw_plan = self._catalog.plan_gc(
                now=observed_at,
                tenant_id=tenant_id,
            )
            snapshot = self._catalog.snapshot(
                captured_at=observed_at,
                tenant_id=tenant_id,
            )
            if raw_plan.catalog_snapshot_checksum == snapshot.snapshot_checksum:
                return (
                    ArtifactCatalogGcPlan.create(
                        generated_at=raw_plan.generated_at,
                        decisions=raw_plan.decisions,
                        catalog_snapshot_checksum=snapshot.snapshot_checksum,
                        policy_version=self._config.policy_version,
                    ),
                    snapshot,
                )
        raise result_error(
            GraphArtifactResultErrorCode.GC_PLAN_STALE,
            field="governance.catalog_snapshot",
        )

    def _advance_operation(
        self,
        operation: GraphArtifactGcOperation,
    ) -> GraphArtifactGcOperation:
        current = self._reload(operation)
        for _ in range(_MAX_OPERATION_TRANSITIONS):
            self._record_transition_usage(current)
            if current.state in _TERMINAL_GC_STATES:
                return current
            try:
                if current.request is None:
                    candidate = self._detach_candidate(current)
                elif current.quarantine is None:
                    quarantine = self._lifecycle.quarantine(current.request)
                    candidate = self._operation(
                        current,
                        state=GraphArtifactGcOperationState.QUARANTINED,
                        quarantine=quarantine,
                    )
                elif current.deletion is None:
                    deletion = self._lifecycle.purge(current.quarantine)
                    candidate = self._operation(
                        current,
                        state=GraphArtifactGcOperationState.PURGED,
                        deletion=deletion,
                    )
                else:
                    candidate = self._operation(
                        current,
                        state=GraphArtifactGcOperationState.COMPLETED,
                    )
                current = self._commit_transition(current, candidate)
            except GraphArtifactResultError as exc:
                if (
                    exc.error_code is GraphArtifactResultErrorCode.GC_PLAN_STALE
                    and current.request is None
                ):
                    stale = self._operation(
                        current,
                        state=GraphArtifactGcOperationState.STALE,
                        request=None,
                        quarantine=None,
                        deletion=None,
                    )
                    return self._commit_transition(current, stale)
                return self._commit_retryable(current, exc.error_code)
            except Exception:
                return self._commit_retryable(
                    current,
                    GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                )
        raise result_error(
            GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
            field="governance.transition_budget",
        )

    def _detach_candidate(
        self,
        current: GraphArtifactGcOperation,
    ) -> GraphArtifactGcOperation:
        intent = current.intent
        detach_request = ArtifactCatalogGcDetachRequest.create(
            plan_checksum=intent.plan_checksum,
            catalog_snapshot_checksum=intent.catalog_snapshot_checksum,
            decision=intent.decision,
            requested_at=intent.prepared_at,
        )
        try:
            receipt = self._catalog.detach_gc_candidate(detach_request)
        except GraphArtifactResultError as exc:
            if (
                exc.error_code is not GraphArtifactResultErrorCode.GC_PLAN_STALE
                or not self._can_recover_detach(current)
            ):
                raise
            receipt = ArtifactCatalogGcDetachReceipt.create(
                request_checksum=detach_request.request_checksum,
                entry=intent.entry,
                claims=intent.claims,
                references=intent.references,
                detached_at=detach_request.requested_at,
            )
        delete_request = GraphArtifactPhysicalDeleteRequest.create(
            operation_id=current.operation_id,
            plan_checksum=intent.plan_checksum,
            decision_checksum=intent.decision.decision_checksum,
            intent_checksum=intent.intent_checksum,
            record=intent.entry.record,
            detach_receipt=receipt,
            requested_at=receipt.detached_at,
        )
        return self._operation(
            current,
            state=GraphArtifactGcOperationState.CATALOG_DETACHED,
            request=delete_request,
        )

    def _can_recover_detach(self, current: GraphArtifactGcOperation) -> bool:
        intent = current.intent
        snapshot = self._catalog.snapshot(
            captured_at=intent.prepared_at,
            tenant_id=intent.tenant_id,
        )
        if (
            any(entry.entry_id == intent.entry.entry_id for entry in snapshot.entries)
            or any(claim.entry_id == intent.entry.entry_id for claim in snapshot.claims)
            or any(
                logical.entry_id == intent.entry.entry_id
                for logical in snapshot.references
            )
        ):
            return False
        return not any(
            operation.operation_id != current.operation_id
            and operation.intent.entry.entry_id == intent.entry.entry_id
            and operation.state
            not in {
                GraphArtifactGcOperationState.PREPARED,
                GraphArtifactGcOperationState.STALE,
            }
            for operation in self._ledger.list_gc_operations(
                tenant_id=intent.tenant_id,
                include_completed=True,
            )
        )

    def _commit_retryable(
        self,
        current: GraphArtifactGcOperation,
        error_code: GraphArtifactResultErrorCode,
    ) -> GraphArtifactGcOperation:
        retryable = self._operation(
            current,
            state=GraphArtifactGcOperationState.RETRYABLE_FAILURE,
            error_code=error_code,
        )
        return self._commit_transition(current, retryable)

    def _commit_transition(
        self,
        current: GraphArtifactGcOperation,
        candidate: GraphArtifactGcOperation,
    ) -> GraphArtifactGcOperation:
        try:
            stored = self._ledger.compare_and_set_gc_operation(
                candidate,
                expected_checksum=current.operation_checksum,
            )
        except GraphArtifactResultError as exc:
            latest = self._ledger.get_gc_operation(
                tenant_id=current.intent.tenant_id,
                operation_id=current.operation_id,
            )
            if (
                exc.error_code
                in {
                    GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                    GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                }
                and latest is not None
                and latest.operation_checksum != current.operation_checksum
            ):
                stored = latest
            else:
                raise
        self._record_transition_usage(stored)
        return stored

    def _operation(
        self,
        current: GraphArtifactGcOperation,
        *,
        state: GraphArtifactGcOperationState,
        request: GraphArtifactPhysicalDeleteRequest | None | object = ...,
        quarantine: object = ...,
        deletion: object = ...,
        error_code: GraphArtifactResultErrorCode | None = None,
    ) -> GraphArtifactGcOperation:
        actual_request = current.request if request is ... else request
        actual_quarantine = current.quarantine if quarantine is ... else quarantine
        actual_deletion = current.deletion if deletion is ... else deletion
        return GraphArtifactGcOperation.create(
            operation_id=current.operation_id,
            state=state,
            intent=current.intent,
            request=actual_request,
            quarantine=actual_quarantine,
            deletion=actual_deletion,
            error_code=(
                error_code
                if state is GraphArtifactGcOperationState.RETRYABLE_FAILURE
                else None
            ),
            updated_at=max(
                self._time(),
                current.updated_at,
                (
                    actual_request.requested_at
                    if isinstance(actual_request, GraphArtifactPhysicalDeleteRequest)
                    else current.updated_at
                ),
                (
                    actual_quarantine.quarantined_at
                    if actual_quarantine is not None
                    and actual_quarantine is not ...
                    else current.updated_at
                ),
                (
                    actual_deletion.deleted_at
                    if actual_deletion is not None and actual_deletion is not ...
                    else current.updated_at
                ),
            ),
        )

    def _record_transition_usage(
        self,
        operation: GraphArtifactGcOperation,
    ) -> GraphArtifactUsageFact:
        state = operation.state
        reason = {
            GraphArtifactGcOperationState.PREPARED: GraphArtifactUsageReason.GC_PREPARED.value,
            GraphArtifactGcOperationState.CATALOG_DETACHED: GraphArtifactUsageReason.GC_CATALOG_DETACHED.value,
            GraphArtifactGcOperationState.QUARANTINED: GraphArtifactUsageReason.GC_QUARANTINED.value,
            GraphArtifactGcOperationState.PURGED: GraphArtifactUsageReason.GC_PURGED.value,
            GraphArtifactGcOperationState.COMPLETED: GraphArtifactUsageReason.GC_COMPLETED.value,
            GraphArtifactGcOperationState.STALE: GraphArtifactUsageReason.GC_STALE.value,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE: (
                operation.error_code.value
                if operation.error_code is not None
                else GraphArtifactResultErrorCode.GC_OPERATION_FAILED.value
            ),
        }[state]
        outcome = (
            GraphArtifactUsageOutcome.STALE
            if state is GraphArtifactGcOperationState.STALE
            else (
                GraphArtifactUsageOutcome.FAILED
                if state is GraphArtifactGcOperationState.RETRYABLE_FAILURE
                else GraphArtifactUsageOutcome.SUCCEEDED
            )
        )
        stage = state.value
        if state is GraphArtifactGcOperationState.RETRYABLE_FAILURE:
            revision = operation.operation_checksum.removeprefix("sha256:")
            stage = f"{stage}/{_operation_phase(operation)}/{reason}/{revision}"
        record = operation.intent.entry.record
        fact = GraphArtifactUsageFact.create(
            kind=GraphArtifactUsageKind.GC_TRANSITION,
            outcome=outcome,
            tenant_id=operation.intent.tenant_id,
            run_id=record.run_id,
            graph_id=record.graph_id,
            node_id=record.node_id,
            artifact_class=record.artifact_class,
            retention_class=record.retention_class,
            policy_version=operation.intent.policy_version,
            operation_id=f"{operation.operation_id}/transition/{stage}",
            physical_bytes=(
                record.byte_size
                if state is GraphArtifactGcOperationState.PURGED
                else 0
            ),
            object_count=(1 if state is GraphArtifactGcOperationState.PURGED else 0),
            reason_code=reason,
            occurred_at=operation.updated_at,
        )
        stored = self._ledger.record_usage(fact)
        if stored != fact:
            raise self._ledger_error("gc_usage")
        return stored

    def _reload(
        self,
        operation: GraphArtifactGcOperation,
    ) -> GraphArtifactGcOperation:
        stored = self._ledger.get_gc_operation(
            tenant_id=operation.intent.tenant_id,
            operation_id=operation.operation_id,
        )
        if stored is None:
            raise result_error(
                GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                field="governance.gc_operation",
            )
        return stored

    def _time(self, value: datetime | None = None) -> datetime:
        return aware_datetime(
            self._clock() if value is None else value,
            "governance.clock",
        )

    def _require_enforce(self, operation: str) -> None:
        if self._config.mode is not GraphArtifactRolloutMode.ENFORCE:
            raise result_error(
                GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID,
                field=f"governance.{operation}",
                mode=self._config.mode.value,
            )

    @staticmethod
    def _ledger_error(field: str) -> GraphArtifactResultError:
        return result_error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            field=f"governance.{field}",
        )


def _operation_phase(operation: GraphArtifactGcOperation) -> str:
    if operation.deletion is not None:
        return "completion"
    if operation.quarantine is not None:
        return "purge"
    if operation.request is not None:
        return "quarantine"
    return "detach"


def _operation_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_GC_OPERATIONS
    ):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="governance.max_operations",
        )
    return value


__all__ = [
    "DEFAULT_MAX_GC_OPERATIONS",
    "GraphArtifactGovernanceRuntime",
    "MAX_GC_OPERATIONS",
]
