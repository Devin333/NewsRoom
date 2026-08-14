from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from framework.events.canonical import checksum_for
from framework.harness.artifacts.governance import (
    DailyGraphArtifactCostReport,
    GraphArtifactAlert,
    GraphArtifactAlertStatus,
    GraphArtifactDeletionTombstone,
    GraphArtifactGcOperation,
    GraphArtifactGcOperationState,
    GraphArtifactGovernanceLedgerPort,
    GraphArtifactQuotaScope,
    GraphArtifactQuotaSnapshot,
    GraphArtifactUsageFact,
    GraphArtifactUsageKind,
    GraphArtifactUsageOutcome,
    graph_artifact_gc_transition_usage_fact,
)
from framework.harness.artifacts.catalog import ArtifactCatalogGcPlan
from framework.harness.runtime.materializer import (
    ResultAttemptLedgerPort,
    ResultCachePort,
    ResultCacheWriteRequest,
    ResultMaterializationOutcome,
    ResultQuotaPort,
    ResultQuotaReconciliationEvidence,
    ResultQuotaReservation,
)
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    checksum,
    datetime_from_json,
    datetime_to_json,
    exact_reference,
    identifier,
    non_negative_int,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    NodeResultBinding,
    NodeResultEnvelope,
    RetentionClass,
)
from framework.harness.runtime.result_policy import PersistenceBudgetSnapshot
from framework.shared.json import json_loads, stable_json_dumps
from framework.shared.time import utc_now


SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION = 2
DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN = 500 * 1024 * 1024
DEFAULT_MAX_ARTIFACTS_PER_RUN = 200
DEFAULT_MAX_MATERIALIZED_BYTES_PER_TENANT = 50 * 1024 * 1024 * 1024
DEFAULT_MAX_ARTIFACTS_PER_TENANT = 20_000
DEFAULT_MAX_MATERIALIZED_BYTES_PER_CLASS = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_ARTIFACTS_PER_CLASS = 10_000
DEFAULT_BUSY_TIMEOUT_SECONDS = 30.0
_SYNCHRONOUS_POLICIES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
_V1_QUOTA_COLUMNS = frozenset(
    {
        "reservation_id",
        "tenant_id",
        "run_id",
        "reservation_key",
        "generation",
        "reserved_bytes",
        "reserved_objects",
        "reservation_checksum",
        "actual_bytes",
        "actual_objects",
        "outcome",
        "settlement_checksum",
        "created_at",
        "settled_at",
    }
)
_V2_QUOTA_DIMENSION_COLUMNS = frozenset(
    {
        "graph_id",
        "node_id",
        "artifact_class",
        "retention_class",
        "policy_version",
    }
)

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS graph_result_store_metadata (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_attempts (
        binding_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        binding_json TEXT NOT NULL,
        binding_checksum TEXT NOT NULL,
        envelope_json TEXT NOT NULL,
        envelope_checksum TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_attempts_run_idx
    ON graph_result_attempts (tenant_id, run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_quota_reservations (
        reservation_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        graph_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        artifact_class TEXT NOT NULL,
        retention_class TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        reservation_key TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK (generation >= 1),
        reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes >= 0),
        reserved_objects INTEGER NOT NULL CHECK (reserved_objects >= 1),
        reservation_checksum TEXT NOT NULL,
        actual_bytes INTEGER,
        actual_objects INTEGER,
        outcome TEXT,
        settlement_checksum TEXT,
        created_at TEXT NOT NULL,
        settled_at TEXT,
        UNIQUE (tenant_id, run_id, reservation_key, generation)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_quota_run_idx
    ON graph_result_quota_reservations (tenant_id, run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_quota_tenant_idx
    ON graph_result_quota_reservations (tenant_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_quota_class_idx
    ON graph_result_quota_reservations (tenant_id, artifact_class)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_quota_reconciliations (
        evidence_checksum TEXT PRIMARY KEY,
        reservation_id TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        FOREIGN KEY (reservation_id)
            REFERENCES graph_result_quota_reservations (reservation_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_quota_reconciliation_reservation_idx
    ON graph_result_quota_reconciliations (reservation_id, observed_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_cache (
        cache_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        request_json TEXT NOT NULL,
        request_checksum TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_cache_expiry_idx
    ON graph_result_cache (tenant_id, expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_usage (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_id TEXT NOT NULL UNIQUE,
        tenant_id TEXT NOT NULL,
        run_id TEXT,
        graph_id TEXT,
        node_id TEXT,
        artifact_class TEXT,
        policy_version TEXT NOT NULL,
        kind TEXT NOT NULL,
        outcome TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        fact_json TEXT NOT NULL,
        fact_checksum TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_usage_window_idx
    ON graph_artifact_usage (tenant_id, occurred_at, sequence)
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_usage_dimensions_idx
    ON graph_artifact_usage (
        tenant_id, run_id, graph_id, node_id, artifact_class,
        policy_version, sequence
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_gc_plans (
        plan_checksum TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        catalog_snapshot_checksum TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        plan_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_gc_plan_tenant_idx
    ON graph_artifact_gc_plans (tenant_id, generated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_gc_operations (
        operation_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        state TEXT NOT NULL,
        operation_json TEXT NOT NULL,
        operation_checksum TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_gc_operation_state_idx
    ON graph_artifact_gc_operations (tenant_id, state, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_gc_tombstones (
        operation_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        entry_id TEXT NOT NULL,
        tombstone_json TEXT NOT NULL,
        tombstone_checksum TEXT NOT NULL UNIQUE,
        completed_at TEXT NOT NULL,
        FOREIGN KEY (operation_id)
            REFERENCES graph_artifact_gc_operations (operation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_cost_reports (
        report_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        usage_watermark INTEGER NOT NULL CHECK (usage_watermark >= 0),
        catalog_snapshot_checksum TEXT NOT NULL,
        report_json TEXT NOT NULL,
        report_checksum TEXT NOT NULL UNIQUE,
        generated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_cost_report_window_idx
    ON graph_artifact_cost_reports (
        tenant_id, window_start, window_end, usage_watermark
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_artifact_alerts (
        alert_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        alert_json TEXT NOT NULL,
        alert_checksum TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_artifact_alert_inbox_idx
    ON graph_artifact_alerts (tenant_id, status, kind, created_at)
    """,
)


class SQLiteGraphResultStore(
    ResultAttemptLedgerPort,
    ResultQuotaPort,
    ResultCachePort,
    GraphArtifactGovernanceLedgerPort,
):
    """Transactional local result ledger, quota authority, and expiring cache."""

    def __init__(
        self,
        database: str | Path,
        *,
        max_materialized_bytes_per_run: int = (
            DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN
        ),
        max_artifacts_per_run: int = DEFAULT_MAX_ARTIFACTS_PER_RUN,
        max_materialized_bytes_per_tenant: int = (
            DEFAULT_MAX_MATERIALIZED_BYTES_PER_TENANT
        ),
        max_artifacts_per_tenant: int = DEFAULT_MAX_ARTIFACTS_PER_TENANT,
        max_materialized_bytes_per_class: int = (
            DEFAULT_MAX_MATERIALIZED_BYTES_PER_CLASS
        ),
        max_artifacts_per_class: int = DEFAULT_MAX_ARTIFACTS_PER_CLASS,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
        synchronous: str = "NORMAL",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        raw_database = str(database)
        if raw_database == ":memory:" or raw_database.startswith("file:"):
            raise ValueError("graph result storage requires a file-backed database")
        timeout = float(busy_timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError(
                "busy_timeout_seconds must be a finite non-negative number"
            )
        policy = str(synchronous).strip().upper()
        if policy not in _SYNCHRONOUS_POLICIES:
            raise ValueError("synchronous must be one of OFF, NORMAL, FULL, or EXTRA")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.max_materialized_bytes_per_run = _positive_int(
            max_materialized_bytes_per_run,
            "max_materialized_bytes_per_run",
        )
        self.max_artifacts_per_run = _positive_int(
            max_artifacts_per_run,
            "max_artifacts_per_run",
        )
        self.max_materialized_bytes_per_tenant = _positive_int(
            max_materialized_bytes_per_tenant,
            "max_materialized_bytes_per_tenant",
        )
        self.max_artifacts_per_tenant = _positive_int(
            max_artifacts_per_tenant,
            "max_artifacts_per_tenant",
        )
        self.max_materialized_bytes_per_class = _positive_int(
            max_materialized_bytes_per_class,
            "max_materialized_bytes_per_class",
        )
        self.max_artifacts_per_class = _positive_int(
            max_artifacts_per_class,
            "max_artifacts_per_class",
        )
        if (
            self.max_materialized_bytes_per_run
            > self.max_materialized_bytes_per_tenant
            or self.max_artifacts_per_run > self.max_artifacts_per_tenant
            or self.max_materialized_bytes_per_class
            > self.max_materialized_bytes_per_tenant
            or self.max_artifacts_per_class > self.max_artifacts_per_tenant
        ):
            raise ValueError("run and class quota limits must fit tenant limits")
        path = Path(database).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.database = str(path)
        self.busy_timeout_seconds = timeout
        self.synchronous = policy
        self._clock = clock
        self._initialize_schema()

    @property
    def durability_policy(self) -> Mapping[str, str | int]:
        return {
            "journal_mode": "WAL",
            "synchronous": self.synchronous,
            "busy_timeout_ms": int(self.busy_timeout_seconds * 1000),
            "host_scope": "single-host",
        }

    def get(self, binding: NodeResultBinding) -> NodeResultEnvelope | None:
        if not isinstance(binding, NodeResultBinding):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="attempt.binding",
            )
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_attempts WHERE binding_key = ?",
                    (_binding_key(binding),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "attempt.get",
            ) from exc
        if row is None:
            return None
        return _attempt_from_row(row, expected_binding=binding)

    def put(self, envelope: NodeResultEnvelope) -> NodeResultEnvelope:
        if not isinstance(envelope, NodeResultEnvelope):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="attempt.envelope",
            )
        binding = envelope.binding
        binding_payload = binding.to_dict()
        envelope_payload = envelope.to_dict()
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_attempts WHERE binding_key = ?",
                    (_binding_key(binding),),
                ).fetchone()
                if row is not None:
                    existing = _attempt_from_row(row, expected_binding=binding)
                    if existing != envelope:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="attempt",
                        )
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_result_attempts (
                        binding_key, tenant_id, run_id, binding_json,
                        binding_checksum, envelope_json, envelope_checksum,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _binding_key(binding),
                        binding.tenant_id,
                        binding.run_id,
                        stable_json_dumps(binding_payload),
                        checksum_for(binding_payload),
                        stable_json_dumps(envelope_payload),
                        checksum_for(envelope_payload),
                        datetime_to_json(self._now()),
                    ),
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "attempt.put",
            ) from exc
        return envelope

    def reserve(
        self,
        *,
        tenant_id: str,
        run_id: str,
        graph_id: str,
        node_id: str,
        artifact_class: ArtifactClass,
        retention_class: RetentionClass,
        policy_version: str,
        reservation_key: str,
        requested_bytes: int,
        object_count: int,
    ) -> ResultQuotaReservation | None:
        tenant = identifier(tenant_id, "quota.tenant_id")
        run = identifier(run_id, "quota.run_id")
        graph = identifier(graph_id, "quota.graph_id")
        node = identifier(node_id, "quota.node_id")
        try:
            artifact_kind = ArtifactClass(artifact_class)
            retention_kind = RetentionClass(retention_class)
        except (TypeError, ValueError) as exc:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.class",
            ) from exc
        policy = exact_reference(policy_version, "quota.policy_version")
        key = reference(reservation_key, "quota.reservation_key")
        requested = non_negative_int(requested_bytes, "quota.requested_bytes")
        objects = _positive_int(object_count, "quota.object_count")
        try:
            with self._write() as connection:
                latest = connection.execute(
                    """
                    SELECT * FROM graph_result_quota_reservations
                    WHERE tenant_id = ? AND run_id = ? AND reservation_key = ?
                    ORDER BY generation DESC LIMIT 1
                    """,
                    (tenant, run, key),
                ).fetchone()
                generation = 1
                if latest is not None:
                    existing, existing_outcome = _reservation_from_row(latest)
                    if (
                        existing.reserved_bytes != requested
                        or existing.object_count != objects
                        or existing.graph_id != graph
                        or existing.node_id != node
                        or existing.artifact_class is not artifact_kind
                        or existing.retention_class is not retention_kind
                        or existing.policy_version != policy
                    ):
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="quota.reservation",
                        )
                    if existing_outcome is not ResultMaterializationOutcome.FAILED:
                        return existing
                    generation = int(latest["generation"]) + 1

                run_usage = _quota_usage(
                    connection,
                    tenant_id=tenant,
                    run_id=run,
                )
                tenant_usage = _quota_usage(connection, tenant_id=tenant)
                class_usage = _quota_usage(
                    connection,
                    tenant_id=tenant,
                    artifact_class=artifact_kind,
                )
                if (
                    run_usage.materialized_bytes + requested
                    > self.max_materialized_bytes_per_run
                    or run_usage.artifact_count + objects
                    > self.max_artifacts_per_run
                    or tenant_usage.materialized_bytes + requested
                    > self.max_materialized_bytes_per_tenant
                    or tenant_usage.artifact_count + objects
                    > self.max_artifacts_per_tenant
                    or class_usage.materialized_bytes + requested
                    > self.max_materialized_bytes_per_class
                    or class_usage.artifact_count + objects
                    > self.max_artifacts_per_class
                ):
                    return None
                reservation = ResultQuotaReservation(
                    reservation_id=_reservation_id(
                        tenant_id=tenant,
                        run_id=run,
                        reservation_key=key,
                        generation=generation,
                    ),
                    tenant_id=tenant,
                    run_id=run,
                    graph_id=graph,
                    node_id=node,
                    artifact_class=artifact_kind,
                    retention_class=retention_kind,
                    policy_version=policy,
                    reservation_key=key,
                    generation=generation,
                    reserved_bytes=requested,
                    object_count=objects,
                )
                payload = _reservation_payload(reservation)
                connection.execute(
                    """
                    INSERT INTO graph_result_quota_reservations (
                        reservation_id, tenant_id, run_id, reservation_key,
                        graph_id, node_id, artifact_class, retention_class,
                        policy_version, generation, reserved_bytes, reserved_objects,
                        reservation_checksum, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation.reservation_id,
                        tenant,
                        run,
                        key,
                        graph,
                        node,
                        artifact_kind.value,
                        retention_kind.value,
                        policy,
                        generation,
                        requested,
                        objects,
                        checksum_for(payload),
                        datetime_to_json(self._now()),
                    ),
                )
                return reservation
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
                "quota.reserve",
            ) from exc

    def settle(
        self,
        reservation: ResultQuotaReservation,
        *,
        actual_bytes: int,
        object_count: int,
        outcome: ResultMaterializationOutcome,
        usage_fact: GraphArtifactUsageFact | None = None,
    ) -> None:
        if not isinstance(reservation, ResultQuotaReservation):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.reservation",
            )
        actual = non_negative_int(actual_bytes, "quota.actual_bytes")
        objects = non_negative_int(object_count, "quota.object_count")
        try:
            normalized_outcome = ResultMaterializationOutcome(outcome)
        except (TypeError, ValueError) as exc:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.outcome",
            ) from exc
        if (
            actual > reservation.reserved_bytes
            or objects > reservation.object_count
            or (
                normalized_outcome is not ResultMaterializationOutcome.SUCCEEDED
                and (actual != 0 or objects != 0)
            )
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                field="quota.settlement",
            )
        if usage_fact is not None:
            _validate_settlement_usage(
                reservation,
                usage_fact,
                actual_bytes=actual,
                object_count=objects,
                outcome=normalized_outcome,
            )
        try:
            with self._write() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM graph_result_quota_reservations
                    WHERE reservation_id = ?
                    """,
                    (reservation.reservation_id,),
                ).fetchone()
                if row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.reservation",
                    )
                stored, stored_outcome = _reservation_from_row(row)
                if stored != reservation:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                        field="quota.reservation",
                    )
                settlement = _settlement_payload(
                    reservation,
                    actual_bytes=actual,
                    object_count=objects,
                    outcome=normalized_outcome,
                )
                if stored_outcome is not None:
                    if (
                        stored_outcome is not normalized_outcome
                        or int(row["actual_bytes"]) != actual
                        or int(row["actual_objects"]) != objects
                        or row["settlement_checksum"] != checksum_for(settlement)
                    ):
                        raise result_error(
                            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                            field="quota.settlement",
                        )
                    if usage_fact is not None:
                        _put_usage_row(connection, usage_fact)
                    return
                settled_at = datetime_to_json(self._now())
                updated = connection.execute(
                    """
                    UPDATE graph_result_quota_reservations
                    SET actual_bytes = ?, actual_objects = ?, outcome = ?,
                        settlement_checksum = ?, settled_at = ?
                    WHERE reservation_id = ? AND outcome IS NULL
                    """,
                    (
                        actual,
                        objects,
                        normalized_outcome.value,
                        checksum_for(settlement),
                        settled_at,
                        reservation.reservation_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.settlement",
                    )
                if usage_fact is not None:
                    _put_usage_row(connection, usage_fact)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                "quota.settle",
            ) from exc

    def reconcile_pending(
        self,
        evidence: ResultQuotaReconciliationEvidence,
    ) -> ResultQuotaReservation:
        if not isinstance(evidence, ResultQuotaReconciliationEvidence):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.reconciliation",
            )
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_quota_reservations "
                    "WHERE reservation_id = ?",
                    (evidence.reservation_id,),
                ).fetchone()
                if row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.reservation",
                    )
                reservation, outcome = _reservation_from_row(row)
                if outcome is not None:
                    return reservation
                created_at = datetime_from_json(row["created_at"], "quota.created_at")
                if evidence.observed_at < created_at:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.reconciliation",
                    )
                evidence_payload = evidence.to_dict()
                existing_evidence = connection.execute(
                    "SELECT evidence_json FROM graph_result_quota_reconciliations "
                    "WHERE evidence_checksum = ?",
                    (evidence.evidence_checksum,),
                ).fetchone()
                if existing_evidence is not None:
                    if json_loads(str(existing_evidence["evidence_json"])) != evidence_payload:
                        raise result_error(
                            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                            field="quota.reconciliation",
                        )
                else:
                    connection.execute(
                        """
                        INSERT INTO graph_result_quota_reconciliations (
                            evidence_checksum, reservation_id, evidence_json,
                            observed_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            evidence.evidence_checksum,
                            evidence.reservation_id,
                            stable_json_dumps(evidence_payload),
                            datetime_to_json(evidence.observed_at),
                        ),
                    )
                if not evidence.proves_absence:
                    return reservation
                settlement = _settlement_payload(
                    reservation,
                    actual_bytes=0,
                    object_count=0,
                    outcome=ResultMaterializationOutcome.FAILED,
                )
                updated = connection.execute(
                    """
                    UPDATE graph_result_quota_reservations
                    SET actual_bytes = 0, actual_objects = 0, outcome = ?,
                        settlement_checksum = ?, settled_at = ?
                    WHERE reservation_id = ? AND outcome IS NULL
                    """,
                    (
                        ResultMaterializationOutcome.FAILED.value,
                        checksum_for(settlement),
                        datetime_to_json(evidence.observed_at),
                        reservation.reservation_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.reconciliation",
                    )
                return reservation
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                "quota.reconciliation",
            ) from exc

    def budget_snapshot(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> PersistenceBudgetSnapshot:
        tenant = identifier(tenant_id, "quota.tenant_id")
        run = identifier(run_id, "quota.run_id")
        try:
            with self._connection() as connection:
                return _quota_usage(
                    connection,
                    tenant_id=tenant,
                    run_id=run,
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
                "quota.usage",
            ) from exc

    def quota_snapshots(
        self,
        *,
        tenant_id: str,
        captured_at: datetime,
    ) -> tuple[GraphArtifactQuotaSnapshot, ...]:
        tenant = identifier(tenant_id, "quota.tenant_id")
        captured = aware_datetime(captured_at, "quota.captured_at")
        totals: dict[
            tuple[GraphArtifactQuotaScope, str | None],
            list[int],
        ] = {(GraphArtifactQuotaScope.TENANT, None): [0, 0, 0, 0]}
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM graph_result_quota_reservations "
                    "WHERE tenant_id = ? ORDER BY reservation_key, generation",
                    (tenant,),
                ).fetchall()
            for row in rows:
                reservation, outcome = _reservation_from_row(row)
                dimensions = (
                    (GraphArtifactQuotaScope.TENANT, None),
                    (GraphArtifactQuotaScope.RUN, reservation.run_id),
                    (
                        GraphArtifactQuotaScope.ARTIFACT_CLASS,
                        reservation.artifact_class.value,
                    ),
                )
                for dimension in dimensions:
                    values = totals.setdefault(dimension, [0, 0, 0, 0])
                    if outcome is None:
                        values[2] += reservation.reserved_bytes
                        values[3] += reservation.object_count
                    elif outcome is ResultMaterializationOutcome.SUCCEEDED:
                        values[0] += int(row["actual_bytes"])
                        values[1] += int(row["actual_objects"])
            snapshots: list[GraphArtifactQuotaSnapshot] = []
            for (scope, scope_value), values in sorted(
                totals.items(),
                key=lambda item: (item[0][0].value, item[0][1] or ""),
            ):
                if scope is GraphArtifactQuotaScope.TENANT:
                    limit_bytes = self.max_materialized_bytes_per_tenant
                    limit_objects = self.max_artifacts_per_tenant
                    run_id = None
                    artifact_class = None
                elif scope is GraphArtifactQuotaScope.RUN:
                    limit_bytes = self.max_materialized_bytes_per_run
                    limit_objects = self.max_artifacts_per_run
                    run_id = scope_value
                    artifact_class = None
                else:
                    limit_bytes = self.max_materialized_bytes_per_class
                    limit_objects = self.max_artifacts_per_class
                    run_id = None
                    artifact_class = ArtifactClass(scope_value)
                snapshots.append(
                    GraphArtifactQuotaSnapshot.create(
                        scope=scope,
                        tenant_id=tenant,
                        run_id=run_id,
                        artifact_class=artifact_class,
                        charged_bytes=values[0],
                        charged_objects=values[1],
                        pending_bytes=values[2],
                        pending_objects=values[3],
                        limit_bytes=limit_bytes,
                        limit_objects=limit_objects,
                        captured_at=captured,
                    )
                )
            return tuple(snapshots)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
                "quota.snapshots",
            ) from exc

    def put_gc_plan(
        self,
        *,
        tenant_id: str,
        plan: ArtifactCatalogGcPlan,
    ) -> ArtifactCatalogGcPlan:
        tenant = identifier(tenant_id, "gc_plan.tenant_id")
        if not isinstance(plan, ArtifactCatalogGcPlan):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_plan",
            )
        if any(item.tenant_id != tenant for item in plan.decisions):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="gc_plan.tenant_id",
            )
        payload = plan.to_dict()
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_plans WHERE plan_checksum = ?",
                    (plan.plan_checksum,),
                ).fetchone()
                if row is not None:
                    existing = _gc_plan_from_row(row)
                    if row["tenant_id"] != tenant or existing != plan:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="gc_plan",
                        )
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_artifact_gc_plans (
                        plan_checksum, tenant_id, catalog_snapshot_checksum,
                        policy_version, generated_at, plan_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.plan_checksum,
                        tenant,
                        plan.catalog_snapshot_checksum,
                        plan.policy_version,
                        datetime_to_json(plan.generated_at),
                        stable_json_dumps(payload),
                    ),
                )
                return plan
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_plan.put",
            ) from exc

    def get_gc_plan(
        self,
        *,
        tenant_id: str,
        plan_checksum: str,
    ) -> ArtifactCatalogGcPlan | None:
        tenant = identifier(tenant_id, "gc_plan.tenant_id")
        normalized = checksum(plan_checksum, "gc_plan.plan_checksum")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_plans "
                    "WHERE plan_checksum = ? AND tenant_id = ?",
                    (normalized, tenant),
                ).fetchone()
            return None if row is None else _gc_plan_from_row(row)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_plan.get",
            ) from exc

    def put_gc_operation(
        self,
        operation: GraphArtifactGcOperation,
        *,
        usage_fact: GraphArtifactUsageFact | None = None,
    ) -> GraphArtifactGcOperation:
        if (
            not isinstance(operation, GraphArtifactGcOperation)
            or operation.state is not GraphArtifactGcOperationState.PREPARED
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_operation",
            )
        _validate_gc_operation_usage(operation, usage_fact)
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_operations "
                    "WHERE operation_id = ?",
                    (operation.operation_id,),
                ).fetchone()
                if row is not None:
                    existing = _gc_operation_from_row(row)
                    if existing != operation:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="gc_operation",
                        )
                    if usage_fact is not None:
                        _put_usage_row(connection, usage_fact)
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_artifact_gc_operations (
                        operation_id, tenant_id, state, operation_json,
                        operation_checksum, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    _gc_operation_row_values(operation),
                )
                if usage_fact is not None:
                    _put_usage_row(connection, usage_fact)
                return operation
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_operation.put",
            ) from exc

    def get_gc_operation(
        self,
        *,
        tenant_id: str,
        operation_id: str,
    ) -> GraphArtifactGcOperation | None:
        tenant = identifier(tenant_id, "gc_operation.tenant_id")
        normalized = reference(operation_id, "gc_operation.operation_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_operations "
                    "WHERE operation_id = ? AND tenant_id = ?",
                    (normalized, tenant),
                ).fetchone()
            return None if row is None else _gc_operation_from_row(row)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_operation.get",
            ) from exc

    def compare_and_set_gc_operation(
        self,
        operation: GraphArtifactGcOperation,
        *,
        expected_checksum: str,
        usage_fact: GraphArtifactUsageFact | None = None,
    ) -> GraphArtifactGcOperation:
        if not isinstance(operation, GraphArtifactGcOperation):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_operation",
            )
        _validate_gc_operation_usage(operation, usage_fact)
        expected = checksum(expected_checksum, "gc_operation.expected_checksum")
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_operations "
                    "WHERE operation_id = ?",
                    (operation.operation_id,),
                ).fetchone()
                if row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                        field="gc_operation.operation_id",
                    )
                current = _gc_operation_from_row(row)
                if current == operation:
                    if usage_fact is not None:
                        _put_usage_row(connection, usage_fact)
                    return current
                if current.operation_checksum != expected:
                    raise result_error(
                        GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                        field="gc_operation.expected_checksum",
                    )
                _validate_gc_transition(current, operation)
                values = _gc_operation_row_values(operation)
                updated = connection.execute(
                    """
                    UPDATE graph_artifact_gc_operations
                    SET tenant_id = ?, state = ?, operation_json = ?,
                        operation_checksum = ?, updated_at = ?
                    WHERE operation_id = ? AND operation_checksum = ?
                    """,
                    (
                        values[1],
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                        operation.operation_id,
                        expected,
                    ),
                )
                if updated.rowcount != 1:
                    raise result_error(
                        GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                        field="gc_operation.compare_and_set",
                    )
                if operation.state is GraphArtifactGcOperationState.COMPLETED:
                    _put_gc_tombstone_row(
                        connection,
                        GraphArtifactDeletionTombstone.from_completed_operation(
                            operation
                        ),
                    )
                if usage_fact is not None:
                    _put_usage_row(connection, usage_fact)
                return operation
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
                "gc_operation.compare_and_set",
            ) from exc

    def list_gc_operations(
        self,
        *,
        tenant_id: str,
        include_completed: bool = False,
    ) -> tuple[GraphArtifactGcOperation, ...]:
        tenant = identifier(tenant_id, "gc_operation.tenant_id")
        if not isinstance(include_completed, bool):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_operation.include_completed",
            )
        statement = (
            "SELECT * FROM graph_artifact_gc_operations WHERE tenant_id = ?"
        )
        parameters: list[Any] = [tenant]
        if not include_completed:
            statement += " AND state != ?"
            parameters.append(GraphArtifactGcOperationState.COMPLETED.value)
        statement += " ORDER BY updated_at, operation_id"
        try:
            with self._connection() as connection:
                rows = connection.execute(statement, tuple(parameters)).fetchall()
            return tuple(_gc_operation_from_row(row) for row in rows)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_operation.list",
            ) from exc

    def put_gc_tombstone(
        self,
        tombstone: GraphArtifactDeletionTombstone,
    ) -> GraphArtifactDeletionTombstone:
        if not isinstance(tombstone, GraphArtifactDeletionTombstone):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_tombstone",
            )
        try:
            with self._write() as connection:
                operation_row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_operations "
                    "WHERE operation_id = ?",
                    (tombstone.operation_id,),
                ).fetchone()
                if operation_row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                        field="gc_tombstone.operation_id",
                    )
                operation = _gc_operation_from_row(operation_row)
                if (
                    operation.state is not GraphArtifactGcOperationState.COMPLETED
                    or GraphArtifactDeletionTombstone.from_completed_operation(
                        operation
                    )
                    != tombstone
                ):
                    raise result_error(
                        GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                        field="gc_tombstone",
                    )
                return _put_gc_tombstone_row(connection, tombstone)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_tombstone.put",
            ) from exc

    def get_gc_tombstone(
        self,
        *,
        tenant_id: str,
        operation_id: str,
    ) -> GraphArtifactDeletionTombstone | None:
        tenant = identifier(tenant_id, "gc_tombstone.tenant_id")
        normalized = reference(operation_id, "gc_tombstone.operation_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_gc_tombstones "
                    "WHERE operation_id = ? AND tenant_id = ?",
                    (normalized, tenant),
                ).fetchone()
            return None if row is None else _gc_tombstone_from_row(row)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "gc_tombstone.get",
            ) from exc

    def record_usage(self, fact: GraphArtifactUsageFact) -> GraphArtifactUsageFact:
        if not isinstance(fact, GraphArtifactUsageFact):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="usage.fact",
            )
        try:
            with self._write() as connection:
                return _put_usage_row(connection, fact)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "usage.record",
            ) from exc

    def list_usage(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        watermark: int | None = None,
    ) -> tuple[GraphArtifactUsageFact, ...]:
        tenant = identifier(tenant_id, "usage.tenant_id")
        start = aware_datetime(window_start, "usage.window_start")
        end = aware_datetime(window_end, "usage.window_end")
        if end <= start:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="usage.window",
            )
        upper = None if watermark is None else non_negative_int(watermark, "usage.watermark")
        statement = (
            "SELECT * FROM graph_artifact_usage "
            "WHERE tenant_id = ? AND occurred_at >= ? AND occurred_at < ?"
        )
        parameters: list[Any] = [
            tenant,
            datetime_to_json(start),
            datetime_to_json(end),
        ]
        if upper is not None:
            statement += " AND sequence <= ?"
            parameters.append(upper)
        statement += " ORDER BY sequence"
        try:
            with self._connection() as connection:
                rows = connection.execute(statement, tuple(parameters)).fetchall()
            return tuple(_usage_from_row(row) for row in rows)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "usage.list",
            ) from exc

    def usage_watermark(self, *, tenant_id: str) -> int:
        tenant = identifier(tenant_id, "usage.tenant_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) AS watermark "
                    "FROM graph_artifact_usage WHERE tenant_id = ?",
                    (tenant,),
                ).fetchone()
            return int(row["watermark"]) if row is not None else 0
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
                "usage.watermark",
            ) from exc

    def put_cost_report(
        self,
        report: DailyGraphArtifactCostReport,
    ) -> DailyGraphArtifactCostReport:
        if not isinstance(report, DailyGraphArtifactCostReport):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="cost_report",
            )
        payload = report.to_dict()
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_cost_reports WHERE report_id = ?",
                    (report.report_id,),
                ).fetchone()
                if row is not None:
                    existing = _cost_report_from_row(row)
                    if existing != report:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="cost_report",
                        )
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_artifact_cost_reports (
                        report_id, tenant_id, window_start, window_end,
                        usage_watermark, catalog_snapshot_checksum,
                        report_json, report_checksum, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report.report_id,
                        report.tenant_id,
                        datetime_to_json(report.window_start),
                        datetime_to_json(report.window_end),
                        report.usage_watermark,
                        report.catalog_snapshot_checksum,
                        stable_json_dumps(payload),
                        report.report_checksum,
                        datetime_to_json(report.generated_at),
                    ),
                )
                return report
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                "cost_report.put",
            ) from exc

    def get_cost_report(
        self,
        *,
        tenant_id: str,
        report_id: str,
    ) -> DailyGraphArtifactCostReport | None:
        tenant = identifier(tenant_id, "cost_report.tenant_id")
        normalized_id = reference(report_id, "cost_report.report_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_cost_reports "
                    "WHERE report_id = ? AND tenant_id = ?",
                    (normalized_id, tenant),
                ).fetchone()
            return None if row is None else _cost_report_from_row(row)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                "cost_report.get",
            ) from exc

    def list_cost_reports(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[DailyGraphArtifactCostReport, ...]:
        tenant = identifier(tenant_id, "cost_report.tenant_id")
        start = aware_datetime(window_start, "cost_report.window_start")
        end = aware_datetime(window_end, "cost_report.window_end")
        if end <= start:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="cost_report.window",
            )
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM graph_artifact_cost_reports
                    WHERE tenant_id = ? AND window_start = ? AND window_end = ?
                    ORDER BY usage_watermark, report_id
                    """,
                    (tenant, datetime_to_json(start), datetime_to_json(end)),
                ).fetchall()
            return tuple(_cost_report_from_row(row) for row in rows)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.COST_REPORT_FAILED,
                "cost_report.list",
            ) from exc

    def put_alert(self, alert: GraphArtifactAlert) -> GraphArtifactAlert:
        if not isinstance(alert, GraphArtifactAlert):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="alert",
            )
        payload = alert.to_dict()
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_alerts WHERE alert_id = ?",
                    (alert.alert_id,),
                ).fetchone()
                if row is not None:
                    existing = _alert_from_row(row)
                    if existing != alert:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="alert",
                        )
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_artifact_alerts (
                        alert_id, tenant_id, kind, status, window_start,
                        window_end, alert_json, alert_checksum, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert.alert_id,
                        alert.tenant_id,
                        alert.kind.value,
                        alert.status.value,
                        datetime_to_json(alert.window_start),
                        datetime_to_json(alert.window_end),
                        stable_json_dumps(payload),
                        alert.alert_checksum,
                        datetime_to_json(alert.created_at),
                        datetime_to_json(alert.created_at),
                    ),
                )
                return alert
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
                "alert.put",
            ) from exc

    def get_alert(
        self,
        *,
        tenant_id: str,
        alert_id: str,
    ) -> GraphArtifactAlert | None:
        tenant = identifier(tenant_id, "alert.tenant_id")
        normalized_id = reference(alert_id, "alert.alert_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_alerts "
                    "WHERE alert_id = ? AND tenant_id = ?",
                    (normalized_id, tenant),
                ).fetchone()
            return None if row is None else _alert_from_row(row)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
                "alert.get",
            ) from exc

    def list_alerts(
        self,
        *,
        tenant_id: str,
        status: GraphArtifactAlertStatus | None = None,
    ) -> tuple[GraphArtifactAlert, ...]:
        tenant = identifier(tenant_id, "alert.tenant_id")
        normalized_status = (
            None if status is None else GraphArtifactAlertStatus(status)
        )
        statement = "SELECT * FROM graph_artifact_alerts WHERE tenant_id = ?"
        parameters: list[Any] = [tenant]
        if normalized_status is not None:
            statement += " AND status = ?"
            parameters.append(normalized_status.value)
        statement += " ORDER BY created_at, alert_id"
        try:
            with self._connection() as connection:
                rows = connection.execute(statement, tuple(parameters)).fetchall()
            return tuple(_alert_from_row(row) for row in rows)
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
                "alert.list",
            ) from exc

    def acknowledge_alert(
        self,
        *,
        tenant_id: str,
        alert_id: str,
        expected_checksum: str,
        acknowledged_at: datetime,
        acknowledged_by: str,
    ) -> GraphArtifactAlert:
        tenant = identifier(tenant_id, "alert.tenant_id")
        normalized_id = reference(alert_id, "alert.alert_id")
        expected = checksum(expected_checksum, "alert.expected_checksum")
        actual_time = aware_datetime(acknowledged_at, "alert.acknowledged_at")
        actor = identifier(acknowledged_by, "alert.acknowledged_by")
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_artifact_alerts "
                    "WHERE alert_id = ? AND tenant_id = ?",
                    (normalized_id, tenant),
                ).fetchone()
                if row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND,
                        field="alert.alert_id",
                    )
                current = _alert_from_row(row)
                if current.status is GraphArtifactAlertStatus.ACKNOWLEDGED:
                    return current.acknowledge(
                        acknowledged_at=actual_time,
                        acknowledged_by=actor,
                    )
                if current.alert_checksum != expected:
                    raise result_error(
                        GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                        field="alert.expected_checksum",
                    )
                acknowledged = current.acknowledge(
                    acknowledged_at=actual_time,
                    acknowledged_by=actor,
                )
                updated = connection.execute(
                    """
                    UPDATE graph_artifact_alerts
                    SET status = ?, alert_json = ?, alert_checksum = ?,
                        updated_at = ?
                    WHERE alert_id = ? AND tenant_id = ? AND alert_checksum = ?
                    """,
                    (
                        acknowledged.status.value,
                        stable_json_dumps(acknowledged.to_dict()),
                        acknowledged.alert_checksum,
                        datetime_to_json(actual_time),
                        normalized_id,
                        tenant,
                        expected,
                    ),
                )
                if updated.rowcount != 1:
                    raise result_error(
                        GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
                        field="alert.acknowledge",
                    )
                return acknowledged
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
                "alert.acknowledge",
            ) from exc

    def write(self, request: ResultCacheWriteRequest) -> str:
        if not isinstance(request, ResultCacheWriteRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="cache.request",
            )
        if not request.cache_key.startswith(f"cache://{request.tenant_id}/"):
            raise result_error(
                GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                field="cache.key",
            )
        now = self._now()
        if request.expires_at <= now:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_WRITE_FAILED,
                "cache.expires_at",
            )
        payload = _cache_request_payload(request)
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_cache WHERE cache_key = ?",
                    (request.cache_key,),
                ).fetchone()
                if row is not None:
                    existing = _cache_request_from_row(row)
                    if existing == request:
                        return request.cache_key
                    if existing.expires_at > now:
                        raise result_error(
                            GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                            field="cache.key",
                        )
                    connection.execute(
                        "DELETE FROM graph_result_cache WHERE cache_key = ?",
                        (request.cache_key,),
                    )
                connection.execute(
                    """
                    INSERT INTO graph_result_cache (
                        cache_key, tenant_id, expires_at, request_json,
                        request_checksum, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.cache_key,
                        request.tenant_id,
                        datetime_to_json(request.expires_at),
                        stable_json_dumps(payload),
                        checksum_for(payload),
                        datetime_to_json(now),
                    ),
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_WRITE_FAILED,
                "cache.write",
            ) from exc
        return request.cache_key

    def read(self, ref: str) -> Mapping[str, Any]:
        cache_key = reference(ref, "cache.ref")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.read",
            ) from exc
        if row is None:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.ref",
            )
        request = _cache_request_from_row(row)
        if request.expires_at <= self._now():
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.expires_at",
            )
        return dict(request.payload)

    def verify_integrity(self) -> None:
        try:
            with self._connection() as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if result is None or str(result[0]).lower() != "ok":
                    raise _error(
                        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                        "sqlite.quick_check",
                    )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.quick_check",
            ) from exc

    def _initialize_schema(self) -> None:
        try:
            with self._connection() as connection:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                if journal_mode.casefold() != "wal":
                    raise _error(
                        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                        "sqlite.journal_mode",
                    )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    schema_version = _stored_schema_version(connection)
                    if schema_version not in (
                        None,
                        1,
                        SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION,
                    ):
                        raise _error(
                            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                            "sqlite.schema_version",
                        )
                    if schema_version is None:
                        _execute_schema(connection)
                        connection.execute(
                            """
                            INSERT INTO graph_result_store_metadata (
                                singleton, schema_version, created_at
                            ) VALUES (1, ?, ?)
                            """,
                            (
                                SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION,
                                datetime_to_json(self._now()),
                            ),
                        )
                    elif schema_version == 1:
                        _migrate_v1_to_v2(connection)
                        _execute_schema(connection)
                        updated = connection.execute(
                            "UPDATE graph_result_store_metadata "
                            "SET schema_version = ? "
                            "WHERE singleton = 1 AND schema_version = 1",
                            (SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION,),
                        )
                        if updated.rowcount != 1:
                            raise _error(
                                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                                "sqlite.schema_version",
                            )
                    else:
                        _execute_schema(connection)
                    _verify_v2_schema(connection)
                    _metadata_created_at(connection)
                    connection.commit()
                except BaseException:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.initialize",
            ) from exc
        self.verify_integrity()

    def _now(self) -> datetime:
        return aware_datetime(self._clock(), "clock")

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            f"PRAGMA busy_timeout={int(self.busy_timeout_seconds * 1000)}"
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA synchronous={self.synchronous}")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise


def _stored_schema_version(connection: sqlite3.Connection) -> int | None:
    metadata = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'graph_result_store_metadata'"
    ).fetchone()
    if metadata is None:
        existing = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if existing:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.metadata",
            )
        return None
    rows = connection.execute(
        "SELECT singleton, schema_version FROM graph_result_store_metadata"
    ).fetchall()
    if len(rows) != 1 or int(rows[0]["singleton"]) != 1:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.metadata",
        )
    value = rows[0]["schema_version"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.schema_version",
        )
    return value


def _metadata_created_at(connection: sqlite3.Connection) -> datetime:
    row = connection.execute(
        "SELECT created_at FROM graph_result_store_metadata WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.metadata",
        )
    try:
        return datetime_from_json(row["created_at"], "sqlite.created_at")
    except GraphArtifactResultError as exc:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.metadata",
        ) from exc


def _execute_schema(connection: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        connection.execute(statement)


def _quota_column_names(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in connection.execute(
            "PRAGMA table_info(graph_result_quota_reservations)"
        ).fetchall()
    )


def _verify_v2_schema(connection: sqlite3.Connection) -> None:
    if _quota_column_names(connection) != (
        _V1_QUOTA_COLUMNS | _V2_QUOTA_DIMENSION_COLUMNS
    ):
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.schema",
        )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    if _quota_column_names(connection) != _V1_QUOTA_COLUMNS:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.migration",
        )
    rows = connection.execute(
        "SELECT * FROM graph_result_quota_reservations "
        "ORDER BY reservation_id"
    ).fetchall()
    for row in rows:
        _validate_v1_reservation(row)
    for statement in (
        "ALTER TABLE graph_result_quota_reservations "
        "ADD COLUMN graph_id TEXT NOT NULL DEFAULT 'legacy-graph'",
        "ALTER TABLE graph_result_quota_reservations "
        "ADD COLUMN node_id TEXT NOT NULL DEFAULT 'legacy-node'",
        "ALTER TABLE graph_result_quota_reservations "
        "ADD COLUMN artifact_class TEXT NOT NULL DEFAULT 'intermediate'",
        "ALTER TABLE graph_result_quota_reservations "
        "ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'run'",
        "ALTER TABLE graph_result_quota_reservations "
        "ADD COLUMN policy_version TEXT NOT NULL "
        "DEFAULT 'graph-artifact-policy@1'",
    ):
        connection.execute(statement)
    migrated_rows = connection.execute(
        "SELECT * FROM graph_result_quota_reservations "
        "ORDER BY reservation_id"
    ).fetchall()
    for row in migrated_rows:
        generation = int(row["generation"])
        reservation = ResultQuotaReservation(
            reservation_id=str(row["reservation_id"]),
            tenant_id=str(row["tenant_id"]),
            run_id=str(row["run_id"]),
            graph_id=str(row["graph_id"]),
            node_id=str(row["node_id"]),
            artifact_class=str(row["artifact_class"]),
            retention_class=str(row["retention_class"]),
            policy_version=str(row["policy_version"]),
            reservation_key=str(row["reservation_key"]),
            generation=generation,
            reserved_bytes=int(row["reserved_bytes"]),
            object_count=int(row["reserved_objects"]),
        )
        connection.execute(
            "UPDATE graph_result_quota_reservations "
            "SET reservation_checksum = ? WHERE reservation_id = ?",
            (checksum_for(_reservation_payload(reservation)), reservation.reservation_id),
        )


def _validate_v1_reservation(row: sqlite3.Row) -> None:
    generation = int(row["generation"])
    reservation_id = str(row["reservation_id"])
    tenant_id = str(row["tenant_id"])
    run_id = str(row["run_id"])
    reservation_key = str(row["reservation_key"])
    reserved_bytes = int(row["reserved_bytes"])
    reserved_objects = int(row["reserved_objects"])
    payload = {
        "reservation_id": reservation_id,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "reservation_key": reservation_key,
        "reserved_bytes": reserved_bytes,
        "object_count": reserved_objects,
    }
    created_at = datetime_from_json(row["created_at"], "quota.created_at")
    if (
        generation < 1
        or reservation_id
        != _reservation_id(
            tenant_id=tenant_id,
            run_id=run_id,
            reservation_key=reservation_key,
            generation=generation,
        )
        or checksum_for(payload) != row["reservation_checksum"]
    ):
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.migration",
        )
    raw_outcome = row["outcome"]
    if raw_outcome is None:
        if any(
            row[name] is not None
            for name in (
                "actual_bytes",
                "actual_objects",
                "settlement_checksum",
                "settled_at",
            )
        ):
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.migration",
            )
        return
    try:
        outcome = ResultMaterializationOutcome(str(raw_outcome))
        actual_bytes = int(row["actual_bytes"])
        actual_objects = int(row["actual_objects"])
        settled_at = datetime_from_json(row["settled_at"], "quota.settled_at")
    except (TypeError, ValueError, GraphArtifactResultError) as exc:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.migration",
        ) from exc
    settlement = {
        "reservation_id": reservation_id,
        "actual_bytes": actual_bytes,
        "object_count": actual_objects,
        "outcome": outcome.value,
    }
    if (
        actual_bytes < 0
        or actual_objects < 0
        or actual_bytes > reserved_bytes
        or actual_objects > reserved_objects
        or (
            outcome is not ResultMaterializationOutcome.SUCCEEDED
            and (actual_bytes != 0 or actual_objects != 0)
        )
        or settled_at < created_at
        or checksum_for(settlement) != row["settlement_checksum"]
    ):
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "sqlite.migration",
        )


def _binding_key(binding: NodeResultBinding) -> str:
    return checksum_for(binding.to_dict())


def _attempt_from_row(
    row: sqlite3.Row,
    *,
    expected_binding: NodeResultBinding,
) -> NodeResultEnvelope:
    try:
        binding_payload = json_loads(str(row["binding_json"]))
        envelope_payload = json_loads(str(row["envelope_json"]))
        if (
            not isinstance(binding_payload, Mapping)
            or not isinstance(envelope_payload, Mapping)
            or checksum_for(binding_payload) != row["binding_checksum"]
            or checksum_for(envelope_payload) != row["envelope_checksum"]
        ):
            raise ValueError("attempt checksum mismatch")
        binding = NodeResultBinding.from_dict(binding_payload)
        envelope = NodeResultEnvelope.from_dict(envelope_payload)
        datetime_from_json(row["created_at"], "attempt.created_at")
        if (
            binding != expected_binding
            or envelope.binding != binding
            or row["binding_key"] != _binding_key(binding)
            or row["tenant_id"] != binding.tenant_id
            or row["run_id"] != binding.run_id
        ):
            raise ValueError("attempt identity mismatch")
        return envelope
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "attempt.record",
        ) from exc


def _reservation_id(
    *,
    tenant_id: str,
    run_id: str,
    reservation_key: str,
    generation: int,
) -> str:
    digest = hashlib.sha256(
        stable_json_dumps(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "reservation_key": reservation_key,
                "generation": generation,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"quota-reservation://{tenant_id}/{digest}/{generation}"


def _reservation_payload(
    reservation: ResultQuotaReservation,
) -> dict[str, Any]:
    return reservation.to_dict()


def _reservation_from_row(
    row: sqlite3.Row,
) -> tuple[ResultQuotaReservation, ResultMaterializationOutcome | None]:
    try:
        generation = int(row["generation"])
        reservation = ResultQuotaReservation(
            reservation_id=str(row["reservation_id"]),
            tenant_id=str(row["tenant_id"]),
            run_id=str(row["run_id"]),
            graph_id=str(row["graph_id"]),
            node_id=str(row["node_id"]),
            artifact_class=str(row["artifact_class"]),
            retention_class=str(row["retention_class"]),
            policy_version=str(row["policy_version"]),
            reservation_key=str(row["reservation_key"]),
            generation=generation,
            reserved_bytes=int(row["reserved_bytes"]),
            object_count=int(row["reserved_objects"]),
        )
        created_at = datetime_from_json(row["created_at"], "quota.created_at")
        if (
            generation < 1
            or reservation.reservation_id
            != _reservation_id(
                tenant_id=reservation.tenant_id,
                run_id=reservation.run_id,
                reservation_key=reservation.reservation_key,
                generation=generation,
            )
            or checksum_for(_reservation_payload(reservation))
            != row["reservation_checksum"]
        ):
            raise ValueError("reservation checksum mismatch")
        raw_outcome = row["outcome"]
        if raw_outcome is None:
            if any(
                row[field] is not None
                for field in (
                    "actual_bytes",
                    "actual_objects",
                    "settlement_checksum",
                    "settled_at",
                )
            ):
                raise ValueError("pending reservation contains settlement")
            return reservation, None
        outcome = ResultMaterializationOutcome(str(raw_outcome))
        actual = int(row["actual_bytes"])
        objects = int(row["actual_objects"])
        settled_at = datetime_from_json(row["settled_at"], "quota.settled_at")
        settlement = _settlement_payload(
            reservation,
            actual_bytes=actual,
            object_count=objects,
            outcome=outcome,
        )
        if (
            actual < 0
            or objects < 0
            or actual > reservation.reserved_bytes
            or objects > reservation.object_count
            or (
                outcome is not ResultMaterializationOutcome.SUCCEEDED
                and (actual != 0 or objects != 0)
            )
            or settled_at < created_at
            or checksum_for(settlement) != row["settlement_checksum"]
        ):
            raise ValueError("settlement checksum mismatch")
        return reservation, outcome
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
            "quota.record",
        ) from exc


def _settlement_payload(
    reservation: ResultQuotaReservation,
    *,
    actual_bytes: int,
    object_count: int,
    outcome: ResultMaterializationOutcome,
) -> dict[str, Any]:
    return {
        "reservation_id": reservation.reservation_id,
        "actual_bytes": actual_bytes,
        "object_count": object_count,
        "outcome": outcome.value,
    }


def _quota_usage(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    run_id: str | None = None,
    artifact_class: ArtifactClass | None = None,
) -> PersistenceBudgetSnapshot:
    if run_id is not None and artifact_class is not None:
        raise ValueError("quota usage accepts one sub-scope")
    where = "tenant_id = ?"
    parameters: list[Any] = [tenant_id]
    if run_id is not None:
        where += " AND run_id = ?"
        parameters.append(run_id)
    if artifact_class is not None:
        where += " AND artifact_class = ?"
        parameters.append(artifact_class.value)
    rows = connection.execute(
        f"""
        SELECT * FROM graph_result_quota_reservations
        WHERE {where}
        ORDER BY reservation_key, generation
        """,
        tuple(parameters),
    ).fetchall()
    materialized_bytes = 0
    artifact_count = 0
    for row in rows:
        reservation, outcome = _reservation_from_row(row)
        if outcome is None:
            materialized_bytes += reservation.reserved_bytes
            artifact_count += reservation.object_count
        elif outcome is ResultMaterializationOutcome.SUCCEEDED:
            materialized_bytes += int(row["actual_bytes"])
            artifact_count += int(row["actual_objects"])
    return PersistenceBudgetSnapshot(
        materialized_bytes=materialized_bytes,
        artifact_count=artifact_count,
    )


def _cache_request_payload(request: ResultCacheWriteRequest) -> dict[str, Any]:
    return {
        "cache_key": request.cache_key,
        "tenant_id": request.tenant_id,
        "payload": dict(request.payload),
        "media_type": request.media_type,
        "content_checksum": request.content_checksum,
        "byte_size": request.byte_size,
        "dependency_digest": request.dependency_digest,
        "policy_version": request.policy_version,
        "expires_at": datetime_to_json(request.expires_at),
    }


def _cache_request_from_row(row: sqlite3.Row) -> ResultCacheWriteRequest:
    try:
        payload = json_loads(str(row["request_json"]))
        if (
            not isinstance(payload, Mapping)
            or checksum_for(payload) != row["request_checksum"]
            or set(payload)
            != {
                "cache_key",
                "tenant_id",
                "payload",
                "media_type",
                "content_checksum",
                "byte_size",
                "dependency_digest",
                "policy_version",
                "expires_at",
            }
        ):
            raise ValueError("cache checksum mismatch")
        request = ResultCacheWriteRequest(
            cache_key=payload["cache_key"],
            tenant_id=payload["tenant_id"],
            payload=payload["payload"],
            media_type=payload["media_type"],
            content_checksum=payload["content_checksum"],
            byte_size=payload["byte_size"],
            dependency_digest=payload["dependency_digest"],
            policy_version=payload["policy_version"],
            expires_at=datetime_from_json(payload["expires_at"], "cache.expires_at"),
        )
        created_at = datetime_from_json(row["created_at"], "cache.created_at")
        if (
            row["cache_key"] != request.cache_key
            or row["tenant_id"] != request.tenant_id
            or row["expires_at"] != datetime_to_json(request.expires_at)
            or not request.cache_key.startswith(f"cache://{request.tenant_id}/")
            or request.expires_at <= created_at
        ):
            raise ValueError("cache identity mismatch")
        return request
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
            "cache.record",
        ) from exc


def _usage_from_row(row: sqlite3.Row) -> GraphArtifactUsageFact:
    try:
        payload = json_loads(str(row["fact_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("usage payload is not an object")
        fact = GraphArtifactUsageFact.from_dict(payload)
        if (
            int(row["sequence"]) < 1
            or row["fact_id"] != fact.fact_id
            or row["tenant_id"] != fact.tenant_id
            or row["run_id"] != fact.run_id
            or row["graph_id"] != fact.graph_id
            or row["node_id"] != fact.node_id
            or row["artifact_class"]
            != (fact.artifact_class.value if fact.artifact_class else None)
            or row["policy_version"] != fact.policy_version
            or row["kind"] != fact.kind.value
            or row["outcome"] != fact.outcome.value
            or row["occurred_at"] != datetime_to_json(fact.occurred_at)
            or row["fact_checksum"] != fact.fact_checksum
        ):
            raise ValueError("usage row identity mismatch")
        return fact
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            "usage.record",
        ) from exc


def _put_usage_row(
    connection: sqlite3.Connection,
    fact: GraphArtifactUsageFact,
) -> GraphArtifactUsageFact:
    row = connection.execute(
        "SELECT * FROM graph_artifact_usage WHERE fact_id = ?",
        (fact.fact_id,),
    ).fetchone()
    if row is not None:
        existing = _usage_from_row(row)
        if not _same_usage_operation(existing, fact):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="usage.fact",
            )
        return existing
    connection.execute(
        """
        INSERT INTO graph_artifact_usage (
            fact_id, tenant_id, run_id, graph_id, node_id,
            artifact_class, policy_version, kind, outcome,
            occurred_at, fact_json, fact_checksum
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fact.fact_id,
            fact.tenant_id,
            fact.run_id,
            fact.graph_id,
            fact.node_id,
            fact.artifact_class.value if fact.artifact_class else None,
            fact.policy_version,
            fact.kind.value,
            fact.outcome.value,
            datetime_to_json(fact.occurred_at),
            stable_json_dumps(fact.to_dict()),
            fact.fact_checksum,
        ),
    )
    return fact


def _same_usage_operation(
    left: GraphArtifactUsageFact,
    right: GraphArtifactUsageFact,
) -> bool:
    left_value = left.to_dict()
    right_value = right.to_dict()
    for value in (left_value, right_value):
        value.pop("occurred_at")
        value.pop("fact_checksum")
    return left_value == right_value


def _validate_settlement_usage(
    reservation: ResultQuotaReservation,
    fact: GraphArtifactUsageFact,
    *,
    actual_bytes: int,
    object_count: int,
    outcome: ResultMaterializationOutcome,
) -> None:
    expected_outcome = {
        ResultMaterializationOutcome.SUCCEEDED: GraphArtifactUsageOutcome.SUCCEEDED,
        ResultMaterializationOutcome.FAILED: GraphArtifactUsageOutcome.FAILED,
        ResultMaterializationOutcome.OMITTED: GraphArtifactUsageOutcome.OMITTED,
    }[outcome]
    if (
        not isinstance(fact, GraphArtifactUsageFact)
        or fact.kind is not GraphArtifactUsageKind.MATERIALIZATION
        or fact.outcome is not expected_outcome
        or fact.tenant_id != reservation.tenant_id
        or fact.run_id != reservation.run_id
        or fact.graph_id != reservation.graph_id
        or fact.node_id != reservation.node_id
        or fact.artifact_class is not reservation.artifact_class
        or fact.retention_class is not reservation.retention_class
        or fact.policy_version != reservation.policy_version
        or fact.physical_bytes != actual_bytes
        or fact.object_count != object_count
    ):
        raise result_error(
            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
            field="quota.usage_fact",
        )


def _gc_plan_from_row(row: sqlite3.Row) -> ArtifactCatalogGcPlan:
    try:
        payload = json_loads(str(row["plan_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("GC plan payload is not an object")
        plan = ArtifactCatalogGcPlan.from_dict(payload)
        if (
            row["plan_checksum"] != plan.plan_checksum
            or row["catalog_snapshot_checksum"]
            != plan.catalog_snapshot_checksum
            or row["policy_version"] != plan.policy_version
            or row["generated_at"] != datetime_to_json(plan.generated_at)
            or any(item.tenant_id != row["tenant_id"] for item in plan.decisions)
        ):
            raise ValueError("GC plan row identity mismatch")
        return plan
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            "gc_plan.record",
        ) from exc


def _gc_operation_row_values(
    operation: GraphArtifactGcOperation,
) -> tuple[str, str, str, str, str, str]:
    return (
        operation.operation_id,
        operation.intent.tenant_id,
        operation.state.value,
        stable_json_dumps(operation.to_dict()),
        operation.operation_checksum,
        datetime_to_json(operation.updated_at),
    )


def _gc_operation_from_row(row: sqlite3.Row) -> GraphArtifactGcOperation:
    try:
        payload = json_loads(str(row["operation_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("GC operation payload is not an object")
        operation = GraphArtifactGcOperation.from_dict(payload)
        if (
            row["operation_id"] != operation.operation_id
            or row["tenant_id"] != operation.intent.tenant_id
            or row["state"] != operation.state.value
            or row["operation_checksum"] != operation.operation_checksum
            or row["updated_at"] != datetime_to_json(operation.updated_at)
        ):
            raise ValueError("GC operation row identity mismatch")
        return operation
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            "gc_operation.record",
        ) from exc


def _validate_gc_transition(
    current: GraphArtifactGcOperation,
    candidate: GraphArtifactGcOperation,
) -> None:
    allowed = {
        GraphArtifactGcOperationState.PREPARED: {
            GraphArtifactGcOperationState.CATALOG_DETACHED,
            GraphArtifactGcOperationState.STALE,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE,
        },
        GraphArtifactGcOperationState.CATALOG_DETACHED: {
            GraphArtifactGcOperationState.QUARANTINED,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE,
        },
        GraphArtifactGcOperationState.QUARANTINED: {
            GraphArtifactGcOperationState.PURGED,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE,
        },
        GraphArtifactGcOperationState.PURGED: {
            GraphArtifactGcOperationState.COMPLETED,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE,
        },
        GraphArtifactGcOperationState.RETRYABLE_FAILURE: {
            GraphArtifactGcOperationState.CATALOG_DETACHED,
            GraphArtifactGcOperationState.QUARANTINED,
            GraphArtifactGcOperationState.PURGED,
            GraphArtifactGcOperationState.COMPLETED,
            GraphArtifactGcOperationState.STALE,
            GraphArtifactGcOperationState.RETRYABLE_FAILURE,
        },
    }
    if (
        current.operation_id != candidate.operation_id
        or current.intent != candidate.intent
        or candidate.state not in allowed.get(current.state, set())
        or candidate.updated_at < current.updated_at
        or (current.request is not None and candidate.request != current.request)
        or (
            current.quarantine is not None
            and candidate.quarantine != current.quarantine
        )
        or (current.deletion is not None and candidate.deletion != current.deletion)
    ):
        raise result_error(
            GraphArtifactResultErrorCode.GC_OPERATION_FAILED,
            field="gc_operation.transition",
        )


def _validate_gc_operation_usage(
    operation: GraphArtifactGcOperation,
    usage_fact: GraphArtifactUsageFact | None,
) -> None:
    if usage_fact is None:
        return
    if usage_fact != graph_artifact_gc_transition_usage_fact(operation):
        raise result_error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            field="gc_operation.usage",
        )


def _put_gc_tombstone_row(
    connection: sqlite3.Connection,
    tombstone: GraphArtifactDeletionTombstone,
) -> GraphArtifactDeletionTombstone:
    row = connection.execute(
        "SELECT * FROM graph_artifact_gc_tombstones WHERE operation_id = ?",
        (tombstone.operation_id,),
    ).fetchone()
    if row is not None:
        existing = _gc_tombstone_from_row(row)
        if existing != tombstone:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="gc_tombstone",
            )
        return existing
    connection.execute(
        """
        INSERT INTO graph_artifact_gc_tombstones (
            operation_id, tenant_id, entry_id, tombstone_json,
            tombstone_checksum, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            tombstone.operation_id,
            tombstone.tenant_id,
            tombstone.entry_id,
            stable_json_dumps(tombstone.to_dict()),
            tombstone.tombstone_checksum,
            datetime_to_json(tombstone.completed_at),
        ),
    )
    return tombstone


def _gc_tombstone_from_row(row: sqlite3.Row) -> GraphArtifactDeletionTombstone:
    try:
        payload = json_loads(str(row["tombstone_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("GC tombstone payload is not an object")
        tombstone = GraphArtifactDeletionTombstone.from_dict(payload)
        if (
            row["operation_id"] != tombstone.operation_id
            or row["tenant_id"] != tombstone.tenant_id
            or row["entry_id"] != tombstone.entry_id
            or row["tombstone_checksum"] != tombstone.tombstone_checksum
            or row["completed_at"] != datetime_to_json(tombstone.completed_at)
        ):
            raise ValueError("GC tombstone row identity mismatch")
        return tombstone
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.GOVERNANCE_LEDGER_FAILED,
            "gc_tombstone.record",
        ) from exc


def _cost_report_from_row(row: sqlite3.Row) -> DailyGraphArtifactCostReport:
    try:
        payload = json_loads(str(row["report_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("cost report payload is not an object")
        report = DailyGraphArtifactCostReport.from_dict(payload)
        if (
            row["report_id"] != report.report_id
            or row["tenant_id"] != report.tenant_id
            or row["window_start"] != datetime_to_json(report.window_start)
            or row["window_end"] != datetime_to_json(report.window_end)
            or int(row["usage_watermark"]) != report.usage_watermark
            or row["catalog_snapshot_checksum"]
            != report.catalog_snapshot_checksum
            or row["report_checksum"] != report.report_checksum
            or row["generated_at"] != datetime_to_json(report.generated_at)
        ):
            raise ValueError("cost report row identity mismatch")
        return report
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.COST_REPORT_FAILED,
            "cost_report.record",
        ) from exc


def _alert_from_row(row: sqlite3.Row) -> GraphArtifactAlert:
    try:
        payload = json_loads(str(row["alert_json"]))
        if not isinstance(payload, Mapping):
            raise ValueError("alert payload is not an object")
        alert = GraphArtifactAlert.from_dict(payload)
        updated_at = datetime_from_json(row["updated_at"], "alert.updated_at")
        if (
            row["alert_id"] != alert.alert_id
            or row["tenant_id"] != alert.tenant_id
            or row["kind"] != alert.kind.value
            or row["status"] != alert.status.value
            or row["window_start"] != datetime_to_json(alert.window_start)
            or row["window_end"] != datetime_to_json(alert.window_end)
            or row["alert_checksum"] != alert.alert_checksum
            or row["created_at"] != datetime_to_json(alert.created_at)
            or updated_at < alert.created_at
            or (
                alert.acknowledged_at is not None
                and updated_at != alert.acknowledged_at
            )
        ):
            raise ValueError("alert row identity mismatch")
        return alert
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.ALERT_LEDGER_FAILED,
            "alert.record",
        ) from exc


def _positive_int(value: Any, field: str) -> int:
    normalized = non_negative_int(value, field)
    if normalized < 1:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return normalized


def _error(
    code: GraphArtifactResultErrorCode,
    field: str,
) -> GraphArtifactResultError:
    return result_error(code, field=field)


__all__ = [
    "DEFAULT_MAX_ARTIFACTS_PER_RUN",
    "DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN",
    "SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION",
    "SQLiteGraphResultStore",
]
