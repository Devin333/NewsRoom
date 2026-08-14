from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import canonical_json_bytes, checksum_for
from framework.harness.runtime import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    NodeResultBinding,
    NodeResultEnvelope,
    NodeResultRequest,
    NodeResultStatus,
    PersistenceDecision,
    PersistenceMode,
    PersistencePolicy,
    PersistenceReason,
    ResultAttemptLedgerPort,
    ResultCachePort,
    ResultCacheWriteRequest,
    ResultMaterializationOutcome,
    ResultMaterializer,
    ResultMetrics,
    ResultProvenance,
    ResultQuotaPort,
    ResultQuotaReconciliationEvidence,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.storage.artifacts import (
    LocalJsonArtifactCatalog,
    SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION,
    SQLiteGraphResultStore,
)
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
CHECKSUM_A = "sha256:" + "a" * 64
CHECKSUM_B = "sha256:" + "b" * 64


def test_attempt_ledger_round_trips_after_restart_and_satisfies_ports(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    envelope = _envelope(_binding())

    assert isinstance(store, ResultAttemptLedgerPort)
    assert isinstance(store, ResultQuotaPort)
    assert isinstance(store, ResultCachePort)
    assert store.get(envelope.binding) is None
    assert store.put(envelope) == envelope
    assert store.put(envelope) == envelope
    assert SQLiteGraphResultStore(database, clock=lambda: NOW).get(
        envelope.binding
    ) == envelope
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_attempt_ledger_serializes_concurrent_first_writer_and_rejects_conflict(
    tmp_path,
) -> None:
    store = SQLiteGraphResultStore(tmp_path / "graph-results.sqlite3")
    first = _envelope(_binding(), candidate_checksum=CHECKSUM_A)
    second = replace(first, candidate_checksum=CHECKSUM_B)

    def put(envelope):
        try:
            stored = store.put(envelope)
        except GraphArtifactResultError as exc:
            return ("error", exc.error_code)
        return ("stored", stored.candidate_checksum)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(put, (first, second)))

    stored = store.get(first.binding)
    assert stored == first or stored == second
    assert {item[0] for item in outcomes} == {"stored", "error"}
    assert (
        "error",
        GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
    ) in outcomes


def test_quota_is_transactional_bounded_and_settlement_is_exactly_once(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(
        database,
        max_materialized_bytes_per_run=100,
        max_artifacts_per_run=2,
        clock=lambda: NOW,
    )
    first = store.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key="quota://tenant-1/first",
        requested_bytes=60,
        object_count=1,
    )
    assert first is not None
    assert store.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key="quota://tenant-1/first",
        requested_bytes=60,
        object_count=1,
    ) == first
    assert store.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).to_dict() == {"materialized_bytes": 60, "artifact_count": 1}
    assert store.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key="quota://tenant-1/too-large",
        requested_bytes=50,
        object_count=1,
    ) is None

    store.settle(
        first,
        actual_bytes=50,
        object_count=1,
        outcome=ResultMaterializationOutcome.SUCCEEDED,
    )
    store.settle(
        first,
        actual_bytes=50,
        object_count=1,
        outcome=ResultMaterializationOutcome.SUCCEEDED,
    )
    restarted = SQLiteGraphResultStore(
        database,
        max_materialized_bytes_per_run=100,
        max_artifacts_per_run=2,
        clock=lambda: NOW,
    )
    assert restarted.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).to_dict() == {"materialized_bytes": 50, "artifact_count": 1}
    second = restarted.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key="quota://tenant-1/second",
        requested_bytes=50,
        object_count=1,
    )
    assert second is not None
    assert restarted.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key="quota://tenant-1/count-limit",
        requested_bytes=0,
        object_count=1,
    ) is None
    with pytest.raises(GraphArtifactResultError) as conflict:
        restarted.settle(
            first,
            actual_bytes=0,
            object_count=0,
            outcome=ResultMaterializationOutcome.FAILED,
        )
    assert conflict.value.error_code is (
        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED
    )


def test_failed_quota_settlement_releases_usage_and_retry_gets_new_generation(
    tmp_path,
) -> None:
    store = SQLiteGraphResultStore(
        tmp_path / "graph-results.sqlite3",
        max_materialized_bytes_per_run=100,
        max_artifacts_per_run=1,
        clock=lambda: NOW,
    )
    first = _reserve(store, key="retry", requested_bytes=80)
    store.settle(
        first,
        actual_bytes=0,
        object_count=0,
        outcome=ResultMaterializationOutcome.FAILED,
    )
    assert store.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).materialized_bytes == 0

    retried = _reserve(store, key="retry", requested_bytes=80)
    assert retried.reservation_id != first.reservation_id
    assert retried.reservation_id.endswith("/2")
    store.settle(
        retried,
        actual_bytes=70,
        object_count=1,
        outcome=ResultMaterializationOutcome.SUCCEEDED,
    )
    assert store.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).to_dict() == {"materialized_bytes": 70, "artifact_count": 1}


def test_pending_quota_reservation_survives_restart_without_double_charge(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    first_store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    reservation = _reserve(first_store, key="pending", requested_bytes=42)

    restarted = SQLiteGraphResultStore(database, clock=lambda: NOW)
    repeated = _reserve(restarted, key="pending", requested_bytes=42)

    assert repeated == reservation
    assert restarted.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).to_dict() == {"materialized_bytes": 42, "artifact_count": 1}


def test_pending_quota_reconciliation_requires_durable_absence_evidence(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    reservation = _reserve(store, key="reconcile", requested_bytes=42)
    present = ResultQuotaReconciliationEvidence.create(
        reservation_id=reservation.reservation_id,
        attempt_committed=True,
        catalog_claim_committed=False,
        cache_entry_committed=False,
        physical_operation_committed=False,
        evidence_refs=("attempt://run-1/analyze/attempt-1",),
        observed_at=NOW,
    )
    absent = ResultQuotaReconciliationEvidence.create(
        reservation_id=reservation.reservation_id,
        attempt_committed=False,
        catalog_claim_committed=False,
        cache_entry_committed=False,
        physical_operation_committed=False,
        evidence_refs=(CHECKSUM_A, CHECKSUM_B),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert store.reconcile_pending(present) == reservation
    assert store.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).materialized_bytes == 42
    assert store.reconcile_pending(absent) == reservation
    assert store.reconcile_pending(absent) == reservation
    assert SQLiteGraphResultStore(database, clock=lambda: NOW).budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).materialized_bytes == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM graph_result_quota_reconciliations"
        ).fetchone()[0] == 2


def test_tenant_and_artifact_class_quota_are_enforced_across_runs(tmp_path) -> None:
    store = SQLiteGraphResultStore(
        tmp_path / "graph-results.sqlite3",
        max_materialized_bytes_per_run=100,
        max_artifacts_per_run=10,
        max_materialized_bytes_per_tenant=150,
        max_artifacts_per_tenant=20,
        max_materialized_bytes_per_class=100,
        max_artifacts_per_class=10,
        clock=lambda: NOW,
    )

    assert _reserve_dimensions(
        store,
        tenant_id="tenant-1",
        run_id="run-1",
        key="evidence-1",
        requested_bytes=80,
        artifact_class=ArtifactClass.EVIDENCE,
    ) is not None
    assert _reserve_dimensions(
        store,
        tenant_id="tenant-1",
        run_id="run-2",
        key="evidence-2",
        requested_bytes=30,
        artifact_class=ArtifactClass.EVIDENCE,
    ) is None
    assert _reserve_dimensions(
        store,
        tenant_id="tenant-1",
        run_id="run-2",
        key="report-1",
        requested_bytes=60,
        artifact_class=ArtifactClass.REPORT,
    ) is not None
    assert _reserve_dimensions(
        store,
        tenant_id="tenant-1",
        run_id="run-3",
        key="report-2",
        requested_bytes=20,
        artifact_class=ArtifactClass.REPORT,
    ) is None
    assert _reserve_dimensions(
        store,
        tenant_id="tenant-2",
        run_id="run-1",
        key="evidence-tenant-2",
        requested_bytes=100,
        artifact_class=ArtifactClass.EVIDENCE,
    ) is not None
    snapshots = store.quota_snapshots(tenant_id="tenant-1", captured_at=NOW)
    by_dimension = {
        (item.scope.value, item.run_id, item.artifact_class): item
        for item in snapshots
    }
    assert by_dimension[("tenant", None, None)].pending_bytes == 140
    assert by_dimension[("run", "run-1", None)].pending_bytes == 80
    assert by_dimension[("run", "run-2", None)].pending_bytes == 60
    assert by_dimension[("artifact_class", None, ArtifactClass.EVIDENCE)].pending_bytes == 80
    assert by_dimension[("artifact_class", None, ArtifactClass.REPORT)].pending_bytes == 60


def test_concurrent_runs_cannot_overbook_one_tenant(tmp_path) -> None:
    store = SQLiteGraphResultStore(
        tmp_path / "graph-results.sqlite3",
        max_materialized_bytes_per_run=100,
        max_materialized_bytes_per_tenant=100,
        max_materialized_bytes_per_class=100,
        clock=lambda: NOW,
    )

    def reserve(index: int):
        return _reserve_dimensions(
            store,
            tenant_id="tenant-1",
            run_id=f"run-{index}",
            key=f"concurrent-{index}",
            requested_bytes=80,
            artifact_class=ArtifactClass.EVIDENCE,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reserve, (1, 2)))

    assert sum(item is not None for item in results) == 1


def test_v1_database_migrates_transactionally_without_rewriting_attempts(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    envelope = _envelope(_binding())
    _create_v1_database(database, envelope=envelope)
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT binding_checksum, envelope_checksum "
            "FROM graph_result_attempts"
        ).fetchone()

    store = SQLiteGraphResultStore(database, clock=lambda: NOW)

    assert store.get(envelope.binding) == envelope
    assert store.budget_snapshot(
        tenant_id="tenant-1",
        run_id="run-1",
    ).to_dict() == {"materialized_bytes": 42, "artifact_count": 1}
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT binding_checksum, envelope_checksum "
            "FROM graph_result_attempts"
        ).fetchone()
        version = connection.execute(
            "SELECT schema_version FROM graph_result_store_metadata"
        ).fetchone()[0]
        dimensions = connection.execute(
            "SELECT graph_id, node_id, artifact_class, retention_class, "
            "policy_version FROM graph_result_quota_reservations"
        ).fetchone()
    assert after == before
    assert version == SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION
    assert dimensions == (
        "legacy-graph",
        "legacy-node",
        "intermediate",
        "run",
        "graph-artifact-policy@1",
    )


def test_partial_v1_migration_is_rejected_without_advancing_version(tmp_path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    _create_v1_database(database, envelope=_envelope(_binding()))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "ALTER TABLE graph_result_quota_reservations "
            "ADD COLUMN graph_id TEXT"
        )
        connection.commit()

    with pytest.raises(GraphArtifactResultError) as partial:
        SQLiteGraphResultStore(database, clock=lambda: NOW)

    assert partial.value.error_code is GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM graph_result_store_metadata"
        ).fetchone()[0] == 1


def test_cache_is_tenant_scoped_restart_safe_conflict_checked_and_expiring(
    tmp_path,
) -> None:
    clock = [NOW]
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: clock[0])
    request = _cache_request()

    assert store.write(request) == request.cache_key
    assert store.write(request) == request.cache_key
    assert SQLiteGraphResultStore(
        database,
        clock=lambda: clock[0],
    ).read(request.cache_key) == request.payload
    with pytest.raises(GraphArtifactResultError) as conflict:
        store.write(replace(request, payload={"value": "different"}))
    assert conflict.value.error_code is GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID
    with pytest.raises(GraphArtifactResultError) as wrong_scope:
        store.write(
            replace(
                request,
                cache_key="cache://tenant-2/cross-scope",
            )
        )
    assert wrong_scope.value.error_code is GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID

    clock[0] = request.expires_at
    with pytest.raises(GraphArtifactResultError) as expired:
        store.read(request.cache_key)
    assert expired.value.error_code is GraphArtifactResultErrorCode.CACHE_READBACK_FAILED


@pytest.mark.parametrize(
    "target",
    ["attempt", "quota", "quota_generation", "cache"],
)
def test_logical_sql_tampering_fails_integrity_checks(tmp_path, target: str) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    binding = _binding()
    if target == "attempt":
        store.put(_envelope(binding))
        statement = (
            "UPDATE graph_result_attempts SET envelope_json = '{\"tampered\":true}'"
        )
    elif target in {"quota", "quota_generation"}:
        _reserve(store, key="tamper", requested_bytes=20)
        if target == "quota":
            statement = (
                "UPDATE graph_result_quota_reservations SET reserved_bytes = 21"
            )
        else:
            statement = "UPDATE graph_result_quota_reservations SET generation = 2"
    else:
        request = _cache_request()
        store.write(request)
        statement = (
            "UPDATE graph_result_cache SET request_json = '{\"tampered\":true}'"
        )
    with sqlite3.connect(database) as connection:
        connection.execute(statement)
        connection.commit()

    with pytest.raises(GraphArtifactResultError):
        if target == "attempt":
            store.get(binding)
        elif target in {"quota", "quota_generation"}:
            store.budget_snapshot(tenant_id="tenant-1", run_id="run-1")
        else:
            store.read(_cache_request().cache_key)


def test_restart_rejects_unsupported_schema_version(tmp_path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    SQLiteGraphResultStore(database, clock=lambda: NOW)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE graph_result_store_metadata SET schema_version = 999"
        )
        connection.commit()

    with pytest.raises(GraphArtifactResultError) as unsupported:
        SQLiteGraphResultStore(database, clock=lambda: NOW)

    assert unsupported.value.error_code is (
        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    )


def test_materializer_uses_durable_store_catalog_lookup_and_internal_artifacts(
    tmp_path,
) -> None:
    database = tmp_path / "graph-results.sqlite3"
    store = SQLiteGraphResultStore(database, clock=lambda: NOW)
    catalog = LocalJsonArtifactCatalog(tmp_path / "catalog")
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "runs")
    materializer = ResultMaterializer(
        policy=PersistencePolicy(GraphArtifactPersistenceConfig()),
        artifact_port=artifact_port,
        catalog=catalog,
        quota=store,
        cache=store,
        attempts=store,
        clock=lambda: NOW,
    )
    request = _node_request(
        binding=_binding(),
        candidate={"data": "x" * (32 * 1024)},
    )

    result = materializer.materialize(request)

    assert result.envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    record = result.envelope.materialized_refs[0]
    assert catalog.get_by_ref(tenant_id="tenant-1", ref=record.ref).record.ref == (
        record.ref
    )
    manifest = artifact_port.manager.read_run_manifest("run-1")
    indexed = next(
        item
        for item in manifest["artifact_index"]
        if item["artifact_id"] == record.artifact_type
    )
    assert indexed["metadata"]["graph_result_ref_only"] is True
    assert indexed["metadata"]["identity_checksum"] == (
        "sha256:" + record.artifact_type.removeprefix("graph-result-")
    )
    restarted = SQLiteGraphResultStore(database, clock=lambda: NOW)
    assert restarted.get(request.binding) == result.envelope


def test_catalog_dedup_returns_canonical_ref_for_later_run(tmp_path) -> None:
    store = SQLiteGraphResultStore(tmp_path / "graph-results.sqlite3", clock=lambda: NOW)
    catalog = LocalJsonArtifactCatalog(tmp_path / "catalog")
    artifact_port = FilesystemHarnessArtifactPort(tmp_path / "runs")
    materializer = ResultMaterializer(
        policy=PersistencePolicy(GraphArtifactPersistenceConfig()),
        artifact_port=artifact_port,
        catalog=catalog,
        quota=store,
        cache=store,
        attempts=store,
        clock=lambda: NOW,
    )
    candidate = {"data": "x" * (32 * 1024)}
    first = materializer.materialize(
        _node_request(binding=_binding(run_id="run-1"), candidate=candidate)
    )
    second = materializer.materialize(
        _node_request(binding=_binding(run_id="run-2"), candidate=candidate)
    )

    first_record = first.envelope.materialized_refs[0]
    second_record = second.envelope.materialized_refs[0]
    assert second_record.ref == first_record.ref
    assert second_record.run_id == "run-2"
    assert catalog.get_by_ref(
        tenant_id="tenant-1",
        ref=second_record.ref,
    ).record.ref == first_record.ref


def _binding(*, run_id: str = "run-1") -> NodeResultBinding:
    return NodeResultBinding(
        tenant_id="tenant-1",
        tenant_scope_ref=CHECKSUM_A,
        run_id=run_id,
        graph_id="graph-1",
        graph_version="graph-1@1",
        node_id="analyze",
        attempt_id="attempt-1",
        parent_checkpoint_ref=f"checkpoint://{run_id}/1",
    )


def _envelope(
    binding: NodeResultBinding,
    *,
    candidate_checksum: str = CHECKSUM_A,
) -> NodeResultEnvelope:
    summary = BoundedSummary.from_text("bounded result")
    projection = {"count": 1}
    candidate_bytes = 17
    return NodeResultEnvelope(
        binding=binding,
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="graph-result@1",
        output_schema_digest=CHECKSUM_A,
        candidate_checksum=candidate_checksum,
        summary=summary,
        inline_projection=projection,
        materialized_refs=(),
        cache_refs=(),
        provenance=ResultProvenance(
            producer_ref="worker@1",
            producer_revision="worker-revision@1",
        ),
        persistence_decision=PersistenceDecision(
            mode=PersistenceMode.INLINE,
            reason=PersistenceReason.BELOW_INLINE_THRESHOLD,
            artifact_class=ArtifactClass.CONTROL,
            retention_class=RetentionClass.RUN,
            estimated_bytes=candidate_bytes,
            reserved_bytes=0,
            context_policy=ContextPolicy.SUMMARY_ONLY,
            required=False,
            policy_version="graph-artifact-policy@1",
        ),
        metrics=ResultMetrics(
            candidate_bytes=candidate_bytes,
            candidate_tokens=(candidate_bytes + 3) // 4,
            summary_bytes=summary.byte_size,
            inline_bytes=len(canonical_json_bytes(projection)),
        ),
        created_at=NOW,
    )


def _reserve(store, *, key: str, requested_bytes: int):
    reservation = store.reserve(
        tenant_id="tenant-1",
        run_id="run-1",
        **_quota_dimensions(),
        reservation_key=f"quota://tenant-1/{key}",
        requested_bytes=requested_bytes,
        object_count=1,
    )
    assert reservation is not None
    return reservation


def _reserve_dimensions(
    store,
    *,
    tenant_id: str,
    run_id: str,
    key: str,
    requested_bytes: int,
    artifact_class: ArtifactClass,
):
    return store.reserve(
        tenant_id=tenant_id,
        run_id=run_id,
        graph_id="graph-1",
        node_id="analyze",
        artifact_class=artifact_class,
        retention_class=RetentionClass.RUN,
        policy_version="graph-artifact-policy@1",
        reservation_key=f"quota://{tenant_id}/{key}",
        requested_bytes=requested_bytes,
        object_count=1,
    )


def _quota_dimensions() -> dict:
    return {
        "graph_id": "graph-1",
        "node_id": "analyze",
        "artifact_class": ArtifactClass.INTERMEDIATE,
        "retention_class": RetentionClass.RUN,
        "policy_version": "graph-artifact-policy@1",
    }


def _create_v1_database(database, *, envelope: NodeResultEnvelope) -> None:
    binding_payload = envelope.binding.to_dict()
    envelope_payload = envelope.to_dict()
    reservation_key = "quota://tenant-1/v1-pending"
    generation = 1
    reservation_id = _v1_reservation_id(
        tenant_id="tenant-1",
        run_id="run-1",
        reservation_key=reservation_key,
        generation=generation,
    )
    reservation_payload = {
        "reservation_id": reservation_id,
        "tenant_id": "tenant-1",
        "run_id": "run-1",
        "reservation_key": reservation_key,
        "reserved_bytes": 42,
        "object_count": 1,
    }
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE graph_result_store_metadata (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                schema_version INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE graph_result_attempts (
                binding_key TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                binding_json TEXT NOT NULL,
                binding_checksum TEXT NOT NULL,
                envelope_json TEXT NOT NULL,
                envelope_checksum TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE graph_result_quota_reservations (
                reservation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
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
            );
            """
        )
        connection.execute(
            "INSERT INTO graph_result_store_metadata "
            "(singleton, schema_version, created_at) VALUES (1, 1, ?)",
            ("2026-08-14T08:00:00Z",),
        )
        connection.execute(
            """
            INSERT INTO graph_result_attempts (
                binding_key, tenant_id, run_id, binding_json,
                binding_checksum, envelope_json, envelope_checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checksum_for(binding_payload),
                envelope.binding.tenant_id,
                envelope.binding.run_id,
                stable_json_dumps(binding_payload),
                checksum_for(binding_payload),
                stable_json_dumps(envelope_payload),
                checksum_for(envelope_payload),
                "2026-08-14T08:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO graph_result_quota_reservations (
                reservation_id, tenant_id, run_id, reservation_key,
                generation, reserved_bytes, reserved_objects,
                reservation_checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reservation_id,
                "tenant-1",
                "run-1",
                reservation_key,
                generation,
                42,
                1,
                checksum_for(reservation_payload),
                "2026-08-14T08:00:00Z",
            ),
        )
        connection.commit()


def _v1_reservation_id(
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


def _cache_request() -> ResultCacheWriteRequest:
    return ResultCacheWriteRequest(
        cache_key="cache://tenant-1/result-1",
        tenant_id="tenant-1",
        payload={"value": "cached"},
        media_type="application/json",
        content_checksum=CHECKSUM_A,
        byte_size=17,
        dependency_digest=CHECKSUM_B,
        policy_version="graph-artifact-policy@1",
        expires_at=NOW + timedelta(hours=1),
    )


def _node_request(
    *,
    binding: NodeResultBinding,
    candidate,
) -> NodeResultRequest:
    return NodeResultRequest(
        binding=binding,
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="research-result@1",
        output_schema_digest=CHECKSUM_A,
        candidate=candidate,
        media_type="application/json",
        summary=BoundedSummary.from_text("research result"),
        inline_projection={"count": 1},
        inline_allowed_fields=("count",),
        provenance=ResultProvenance(
            producer_ref="research-worker@1",
            producer_revision="research-worker-revision@1",
        ),
        artifact_class=ArtifactClass.INTERMEDIATE,
        retention_class=RetentionClass.RUN,
        sensitivity=ResultSensitivity.INTERNAL,
        required_for_replay=False,
        required_for_publication=False,
        reusable=False,
        side_effect_free=True,
        dependency_digest=None,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        created_at=NOW,
    )
