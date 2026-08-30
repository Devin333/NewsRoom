from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Self

from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    DailyGraphArtifactCostReport,
    GraphArtifactAlert,
    GraphArtifactAlertStatus,
    GraphArtifactGcOperation,
    GraphArtifactGovernanceRuntime,
    GraphArtifactQuotaSnapshot,
)
from framework.harness.artifacts.catalog import (
    ArtifactCatalogGcPlan,
    ArtifactCatalogReconciliationPlan,
)
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    checksum,
    datetime_to_json,
    identifier,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_policy import GraphArtifactRolloutMode


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class ResearchGraphArtifactGcApplyResult:
    tenant_id: str
    plan_checksum: str
    operations: tuple[GraphArtifactGcOperation, ...]
    result_checksum: str

    def __post_init__(self) -> None:
        tenant = identifier(self.tenant_id, "governance_result.tenant_id")
        plan = reference(self.plan_checksum, "governance_result.plan_checksum")
        if not isinstance(self.operations, tuple) or not all(
            isinstance(operation, GraphArtifactGcOperation)
            for operation in self.operations
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="governance_result.operations",
            )
        operations = tuple(
            sorted(self.operations, key=lambda operation: operation.operation_id)
        )
        if any(
            operation.intent.tenant_id != tenant
            or operation.intent.plan_checksum != plan
            for operation in operations
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="governance_result.operations",
            )
        expected = checksum_for(
            _gc_apply_projection(
                tenant_id=tenant,
                plan_checksum=plan,
                operations=operations,
            )
        )
        if checksum(
            self.result_checksum,
            "governance_result.result_checksum",
        ) != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="governance_result.result_checksum",
            )
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "plan_checksum", plan)
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "result_checksum", expected)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        plan_checksum: str,
        operations: tuple[GraphArtifactGcOperation, ...],
    ) -> Self:
        projection = _gc_apply_projection(
            tenant_id=tenant_id,
            plan_checksum=plan_checksum,
            operations=operations,
        )
        return cls(
            tenant_id=tenant_id,
            plan_checksum=plan_checksum,
            operations=operations,
            result_checksum=checksum_for(projection),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_gc_apply_projection(
                tenant_id=self.tenant_id,
                plan_checksum=self.plan_checksum,
                operations=self.operations,
            ),
            "result_checksum": self.result_checksum,
        }


@dataclass(frozen=True, slots=True)
class ResearchGraphArtifactQuotaInspection:
    tenant_id: str
    captured_at: datetime
    snapshots: tuple[GraphArtifactQuotaSnapshot, ...]
    result_checksum: str

    def __post_init__(self) -> None:
        tenant = identifier(self.tenant_id, "quota_inspection.tenant_id")
        captured = aware_datetime(
            self.captured_at,
            "quota_inspection.captured_at",
        )
        if not isinstance(self.snapshots, tuple) or not self.snapshots or not all(
            isinstance(snapshot, GraphArtifactQuotaSnapshot)
            for snapshot in self.snapshots
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota_inspection.snapshots",
            )
        snapshots = tuple(sorted(self.snapshots, key=_quota_snapshot_sort_key))
        if any(
            snapshot.tenant_id != tenant or snapshot.captured_at != captured
            for snapshot in snapshots
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="quota_inspection.snapshots",
            )
        expected = checksum_for(
            _quota_projection(
                tenant_id=tenant,
                captured_at=captured,
                snapshots=snapshots,
            )
        )
        if checksum(self.result_checksum, "quota_inspection.result_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="quota_inspection.result_checksum",
            )
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "captured_at", captured)
        object.__setattr__(self, "snapshots", snapshots)
        object.__setattr__(self, "result_checksum", expected)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        snapshots: tuple[GraphArtifactQuotaSnapshot, ...],
    ) -> Self:
        if not snapshots:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota_inspection.snapshots",
            )
        captured_at = snapshots[0].captured_at
        projection = _quota_projection(
            tenant_id=tenant_id,
            captured_at=captured_at,
            snapshots=snapshots,
        )
        return cls(
            tenant_id=tenant_id,
            captured_at=captured_at,
            snapshots=snapshots,
            result_checksum=checksum_for(projection),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_quota_projection(
                tenant_id=self.tenant_id,
                captured_at=self.captured_at,
                snapshots=self.snapshots,
            ),
            "result_checksum": self.result_checksum,
        }


@dataclass(frozen=True, slots=True)
class ResearchGraphArtifactReconciliation:
    tenant_id: str
    plan: ArtifactCatalogReconciliationPlan
    result_checksum: str

    def __post_init__(self) -> None:
        tenant = identifier(self.tenant_id, "reconciliation.tenant_id")
        if not isinstance(self.plan, ArtifactCatalogReconciliationPlan):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="reconciliation.plan",
            )
        expected = checksum_for(
            {"tenant_id": tenant, "plan": self.plan.to_dict()}
        )
        if checksum(self.result_checksum, "reconciliation.result_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="reconciliation.result_checksum",
            )
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "result_checksum", expected)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        plan: ArtifactCatalogReconciliationPlan,
    ) -> Self:
        return cls(
            tenant_id=tenant_id,
            plan=plan,
            result_checksum=checksum_for(
                {"tenant_id": tenant_id, "plan": plan.to_dict()}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "plan": self.plan.to_dict(),
            "result_checksum": self.result_checksum,
        }


@dataclass(frozen=True, slots=True)
class ResearchGraphArtifactAlertList:
    tenant_id: str
    status: GraphArtifactAlertStatus | None
    alerts: tuple[GraphArtifactAlert, ...]
    result_checksum: str

    def __post_init__(self) -> None:
        tenant = identifier(self.tenant_id, "alert_list.tenant_id")
        status = (
            GraphArtifactAlertStatus(self.status)
            if self.status is not None
            else None
        )
        if not isinstance(self.alerts, tuple) or not all(
            isinstance(alert, GraphArtifactAlert) for alert in self.alerts
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="alert_list.alerts",
            )
        alerts = tuple(sorted(self.alerts, key=lambda alert: alert.alert_id))
        if any(
            alert.tenant_id != tenant
            or (status is not None and alert.status is not status)
            for alert in alerts
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="alert_list.alerts",
            )
        expected = checksum_for(
            _alert_list_projection(
                tenant_id=tenant,
                status=status,
                alerts=alerts,
            )
        )
        if checksum(self.result_checksum, "alert_list.result_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="alert_list.result_checksum",
            )
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "alerts", alerts)
        object.__setattr__(self, "result_checksum", expected)

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        status: GraphArtifactAlertStatus | None,
        alerts: tuple[GraphArtifactAlert, ...],
    ) -> Self:
        projection = _alert_list_projection(
            tenant_id=tenant_id,
            status=status,
            alerts=alerts,
        )
        return cls(
            tenant_id=tenant_id,
            status=status,
            alerts=alerts,
            result_checksum=checksum_for(projection),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_alert_list_projection(
                tenant_id=self.tenant_id,
                status=self.status,
                alerts=self.alerts,
            ),
            "result_checksum": self.result_checksum,
        }


class ResearchGraphArtifactGovernanceService:
    """Tenant-scoped application boundary for deterministic artifact governance."""

    def __init__(self, runtime: GraphArtifactGovernanceRuntime) -> None:
        if not isinstance(runtime, GraphArtifactGovernanceRuntime):
            raise TypeError("runtime must be GraphArtifactGovernanceRuntime")
        self._runtime = runtime

    @property
    def runtime(self) -> GraphArtifactGovernanceRuntime:
        return self._runtime

    def plan_gc(
        self,
        *,
        tenant_id: str,
        observed_at: datetime | None = None,
    ) -> ArtifactCatalogGcPlan:
        if self._runtime.config.mode is GraphArtifactRolloutMode.ENFORCE:
            return self._runtime.prepare_gc(
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        return self._runtime.plan_gc(
            tenant_id=tenant_id,
            observed_at=observed_at,
        )

    def apply_gc(
        self,
        *,
        tenant_id: str,
        plan_checksum: str,
        confirmed: bool,
        max_operations: int,
    ) -> ResearchGraphArtifactGcApplyResult:
        operations = self._runtime.apply_gc(
            tenant_id=tenant_id,
            plan_checksum=plan_checksum,
            confirmed=confirmed,
            max_operations=max_operations,
        )
        return ResearchGraphArtifactGcApplyResult.create(
            tenant_id=tenant_id,
            plan_checksum=plan_checksum,
            operations=operations,
        )

    def generate_cost_report(
        self,
        *,
        tenant_id: str,
        day: date,
        generated_at: datetime | None = None,
    ) -> DailyGraphArtifactCostReport:
        window_start = _utc_day_start(day)
        report = self._runtime.generate_cost_report(
            tenant_id=tenant_id,
            window_start=window_start,
            generated_at=generated_at,
        )
        reconciliation = self._runtime.reconcile_catalog(
            tenant_id=tenant_id,
            observed_at=report.generated_at,
        )
        self._runtime.evaluate_alerts(
            tenant_id=tenant_id,
            report=report,
            gc_plan=self._runtime.plan_gc(
                tenant_id=tenant_id,
                observed_at=report.generated_at,
            ),
            reconciliation=reconciliation,
        )
        return report

    def inspect_quota(
        self,
        *,
        tenant_id: str,
        captured_at: datetime | None = None,
    ) -> ResearchGraphArtifactQuotaInspection:
        return ResearchGraphArtifactQuotaInspection.create(
            tenant_id=tenant_id,
            snapshots=self._runtime.quota_snapshots(
                tenant_id=tenant_id,
                captured_at=captured_at,
            ),
        )

    def reconcile(
        self,
        *,
        tenant_id: str,
        observed_at: datetime | None = None,
    ) -> ResearchGraphArtifactReconciliation:
        plan = self._runtime.reconcile_catalog(
            tenant_id=tenant_id,
            observed_at=observed_at,
        )
        self._runtime.evaluate_reconciliation_alerts(
            tenant_id=tenant_id,
            reconciliation=plan,
        )
        return ResearchGraphArtifactReconciliation.create(
            tenant_id=tenant_id,
            plan=plan,
        )

    def list_alerts(
        self,
        *,
        tenant_id: str,
        status: GraphArtifactAlertStatus | None = None,
    ) -> ResearchGraphArtifactAlertList:
        normalized_status = (
            GraphArtifactAlertStatus(status) if status is not None else None
        )
        return ResearchGraphArtifactAlertList.create(
            tenant_id=tenant_id,
            status=normalized_status,
            alerts=self._runtime.list_alerts(
                tenant_id=tenant_id,
                status=normalized_status,
            ),
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
        return self._runtime.acknowledge_alert(
            tenant_id=tenant_id,
            alert_id=alert_id,
            expected_checksum=expected_checksum,
            acknowledged_by=acknowledged_by,
            acknowledged_at=acknowledged_at,
        )


def _utc_day_start(value: date) -> datetime:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="cost_report.day",
        )
    return datetime.combine(value, time.min, tzinfo=UTC)


def _gc_apply_projection(
    *,
    tenant_id: str,
    plan_checksum: str,
    operations: tuple[GraphArtifactGcOperation, ...],
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "plan_checksum": plan_checksum,
        "operations": [
            operation.to_dict()
            for operation in sorted(
                operations,
                key=lambda operation: operation.operation_id,
            )
        ],
    }


def _quota_projection(
    *,
    tenant_id: str,
    captured_at: datetime,
    snapshots: tuple[GraphArtifactQuotaSnapshot, ...],
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "captured_at": datetime_to_json(captured_at),
        "snapshots": [
            snapshot.to_dict()
            for snapshot in sorted(snapshots, key=_quota_snapshot_sort_key)
        ],
    }


def _quota_snapshot_sort_key(
    snapshot: GraphArtifactQuotaSnapshot,
) -> tuple[str, str, str]:
    return (
        snapshot.scope.value,
        snapshot.run_id or "",
        snapshot.artifact_class.value if snapshot.artifact_class is not None else "",
    )


def _alert_list_projection(
    *,
    tenant_id: str,
    status: GraphArtifactAlertStatus | None,
    alerts: tuple[GraphArtifactAlert, ...],
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "status": status.value if status is not None else None,
        "alerts": [
            alert.to_dict()
            for alert in sorted(alerts, key=lambda alert: alert.alert_id)
        ],
    }


__all__ = [
    "ResearchGraphArtifactAlertList",
    "ResearchGraphArtifactGcApplyResult",
    "ResearchGraphArtifactGovernanceService",
    "ResearchGraphArtifactQuotaInspection",
    "ResearchGraphArtifactReconciliation",
]
