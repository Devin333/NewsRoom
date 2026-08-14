from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.artifacts import (
    GraphArtifactAlert,
    GraphArtifactAlertKind,
    GraphArtifactAlertReason,
    GraphArtifactAlertStatus,
    GraphArtifactCostAggregate,
    GraphArtifactCostDimension,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    GraphArtifactUsagePort,
    GraphArtifactUsageReason,
)
from framework.harness.artifacts.governance import DailyGraphArtifactCostReport
from framework.harness.runtime import (
    ArtifactClass,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    RetentionClass,
)
from infrastructure.storage.artifacts import SQLiteGraphResultStore


DAY = datetime(2026, 8, 14, tzinfo=UTC)
NOW = DAY + timedelta(hours=8)
CHECKSUM = "sha256:" + "a" * 64


def test_usage_facts_are_idempotent_scoped_and_watermarked_after_restart(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    first = _usage(
        operation_id="materialization://attempt-1",
        occurred_at=NOW,
    )
    second = _usage(
        operation_id="materialization://attempt-2",
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert isinstance(store, GraphArtifactUsagePort)
    assert store.record_usage(first) == first
    assert store.record_usage(first) == first
    first_watermark = store.usage_watermark(tenant_id="tenant-1")
    assert first_watermark == 1
    assert store.record_usage(second) == second
    restarted = SQLiteGraphResultStore(database, clock=lambda: NOW)
    assert restarted.usage_watermark(tenant_id="tenant-1") == 2
    assert restarted.list_usage(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        watermark=first_watermark,
    ) == (first,)
    assert restarted.list_usage(
        tenant_id="tenant-2",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
    ) == ()


def test_usage_identity_conflict_and_sql_tamper_fail_closed(tmp_path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    fact = _usage(
        operation_id="materialization://attempt-1",
        occurred_at=NOW,
    )
    conflict = GraphArtifactUsageFact.create(
        **{
            **_usage_values(
                operation_id="materialization://attempt-1",
                occurred_at=NOW,
            ),
            "outcome": GraphArtifactUsageOutcome.FAILED,
            "reason_code": GraphArtifactResultErrorCode.ARTIFACT_WRITE_FAILED.value,
        }
    )
    store.record_usage(fact)

    with pytest.raises(GraphArtifactResultError) as duplicate:
        store.record_usage(conflict)
    assert duplicate.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE graph_artifact_usage SET fact_json = '{\"tampered\":true}'"
        )
        connection.commit()
    with pytest.raises(GraphArtifactResultError) as tampered:
        store.list_usage(
            tenant_id="tenant-1",
            window_start=DAY,
            window_end=DAY + timedelta(days=1),
        )
    assert tampered.value.error_code is GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED


def test_cost_report_revisions_are_immutable_and_tenant_scoped(tmp_path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    first = _report(watermark=1, generated_at=DAY + timedelta(days=1))
    second = _report(
        watermark=2,
        generated_at=DAY + timedelta(days=1, seconds=1),
    )

    assert store.put_cost_report(first) == first
    assert store.put_cost_report(first) == first
    assert store.put_cost_report(second) == second
    assert SQLiteGraphResultStore(database, clock=lambda: NOW).list_cost_reports(
        tenant_id="tenant-1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
    ) == (first, second)
    assert store.get_cost_report(
        tenant_id="tenant-2",
        report_id=first.report_id,
    ) is None
    with pytest.raises(GraphArtifactResultError) as conflict:
        store.put_cost_report(replace(first, generated_at=first.generated_at + timedelta(seconds=1)))
    assert conflict.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT


def test_alert_acknowledgement_is_compare_and_set_idempotent_and_scoped(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    alert = _alert()
    store.put_alert(alert)

    def acknowledge(actor: str):
        try:
            return store.acknowledge_alert(
                tenant_id="tenant-1",
                alert_id=alert.alert_id,
                expected_checksum=alert.alert_checksum,
                acknowledged_at=NOW + timedelta(seconds=1),
                acknowledged_by=actor,
            )
        except GraphArtifactResultError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(acknowledge, ("operator-1", "operator-2")))

    acknowledged = tuple(
        item for item in outcomes if isinstance(item, GraphArtifactAlert)
    )
    assert len(acknowledged) == 1
    assert GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT in outcomes
    stored = SQLiteGraphResultStore(database, clock=lambda: NOW).get_alert(
        tenant_id="tenant-1",
        alert_id=alert.alert_id,
    )
    assert stored == acknowledged[0]
    assert stored is not None
    assert store.acknowledge_alert(
        tenant_id="tenant-1",
        alert_id=alert.alert_id,
        expected_checksum=alert.alert_checksum,
        acknowledged_at=stored.acknowledged_at,
        acknowledged_by=stored.acknowledged_by,
    ) == stored
    assert store.get_alert(tenant_id="tenant-2", alert_id=alert.alert_id) is None


def _usage_values(*, operation_id: str, occurred_at: datetime) -> dict:
    return {
        "kind": GraphArtifactUsageKind.MATERIALIZATION,
        "outcome": GraphArtifactUsageOutcome.SUCCEEDED,
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "graph_id": "graph-1",
        "node_id": "analyze",
        "artifact_class": ArtifactClass.EVIDENCE,
        "retention_class": RetentionClass.EVIDENCE,
        "policy_version": "graph-artifact-policy@1",
        "operation_id": operation_id,
        "logical_bytes": 17,
        "physical_bytes": 17,
        "object_count": 1,
        "reason_code": GraphArtifactUsageReason.MATERIALIZED_RESULT.value,
        "occurred_at": occurred_at,
    }


def _usage(*, operation_id: str, occurred_at: datetime) -> GraphArtifactUsageFact:
    return GraphArtifactUsageFact.create(
        **_usage_values(operation_id=operation_id, occurred_at=occurred_at)
    )


def _report(
    *,
    watermark: int,
    generated_at: datetime,
) -> DailyGraphArtifactCostReport:
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
        logical_bytes=17,
        logical_count=1,
        unique_physical_bytes=17,
        unique_physical_count=1,
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
        usage_watermark=watermark,
        aggregates=(aggregate,),
        generated_at=generated_at,
    )


def _alert() -> GraphArtifactAlert:
    return GraphArtifactAlert.create(
        kind=GraphArtifactAlertKind.RUN_QUOTA_PRESSURE,
        status=GraphArtifactAlertStatus.OPEN,
        tenant_id="tenant-1",
        scope_ref="run://run-1",
        policy_version="graph-artifact-policy@1",
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        observed_value=80,
        limit_value=100,
        reason_code=GraphArtifactAlertReason.QUOTA_WARNING_THRESHOLD.value,
        created_at=NOW,
        acknowledged_at=None,
        acknowledged_by=None,
    )
