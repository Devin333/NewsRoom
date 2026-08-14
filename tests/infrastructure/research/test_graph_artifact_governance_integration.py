from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    GraphArtifactGcOperationState,
    GraphArtifactGovernanceRuntime,
    GraphArtifactQuotaScope,
    GraphArtifactUsageKind,
    GraphArtifactUsageReason,
    GraphTerminalManifest,
)
from framework.harness.artifacts.catalog import (
    ArtifactCatalogGcAction,
    ArtifactCatalogGcReason,
    ArtifactLifecycleAuthorization,
    ArtifactLifecycleAuthorityKind,
    ArtifactReferenceRetirementReason,
    ArtifactReferenceRetirementRequest,
)
from framework.harness.runtime import (
    ArtifactClass,
    BoundedSummary,
    ContextPolicy,
    GraphArtifactPersistenceConfig,
    GraphArtifactRetentionSettings,
    GraphArtifactRolloutMode,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    NodeResultBinding,
    NodeResultRequest,
    NodeResultStatus,
    PersistenceMode,
    PersistencePolicy,
    ResultMaterializer,
    ResultMaterializationOutcome,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from infrastructure.research import (
    FilesystemGraphArtifactLifecycle,
    FilesystemHarnessArtifactPort,
)
from infrastructure.storage.artifacts import (
    LocalJsonArtifactCatalog,
    SQLiteGraphResultStore,
)


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
EXPIRED_AT = NOW + timedelta(days=2)
TENANT_ID = "tenant-governance-e2e"
TENANT_SCOPE = checksum_for(TENANT_ID)


@dataclass
class _CrashAfterQuarantine:
    delegate: FilesystemGraphArtifactLifecycle
    pending: bool = True

    def quarantine(self, request):
        receipt = self.delegate.quarantine(request)
        if self.pending:
            self.pending = False
            raise RuntimeError("injected crash after quarantine")
        return receipt

    def purge(self, receipt):
        return self.delegate.purge(receipt)


def test_cross_run_dedup_stale_plan_and_restart_safe_physical_gc(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    catalog_root = root / "_records" / "graph_artifact_catalog"
    database = tmp_path / "graph-results.sqlite3"
    config = _config()
    artifact_port = FilesystemHarnessArtifactPort(root)
    catalog = LocalJsonArtifactCatalog(catalog_root)
    store = _store(database)
    materializer = _materializer(
        config=config,
        artifact_port=artifact_port,
        catalog=catalog,
        store=store,
    )
    lifecycle = FilesystemGraphArtifactLifecycle(
        root,
        artifact_port=artifact_port,
        clock=lambda: EXPIRED_AT + timedelta(hours=1),
    )
    runtime = GraphArtifactGovernanceRuntime(
        catalog=catalog,
        lifecycle=lifecycle,
        ledger=store,
        config=config,
        clock=lambda: EXPIRED_AT,
    )
    candidate = {"data": "shared-evidence-" + "x" * (40 * 1024)}

    first = materializer.materialize(
        _request(run_id="run-1", attempt_id="attempt-1", candidate=candidate)
    ).envelope
    second = materializer.materialize(
        _request(run_id="run-2", attempt_id="attempt-2", candidate=candidate)
    ).envelope
    replay = materializer.materialize(
        _request(
            run_id="run-replay",
            attempt_id="attempt-replay",
            candidate={"data": "replay-" + "y" * (40 * 1024)},
            artifact_class=ArtifactClass.TRANSCRIPT,
            required_for_replay=True,
        )
    ).envelope
    _commit_terminal_manifest(artifact_port, "run-1")
    _commit_terminal_manifest(artifact_port, "run-replay")

    first_record = first.materialized_refs[0]
    second_record = second.materialized_refs[0]
    replay_record = replay.materialized_refs[0]
    evidence_entry = catalog.get_by_ref(
        tenant_id=TENANT_ID,
        ref=first_record.ref,
    )
    assert first.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert second_record.ref == first_record.ref
    assert len(catalog.list_references(evidence_entry.entry_id)) == 2

    protected = runtime.plan_gc(
        tenant_id=TENANT_ID,
        observed_at=EXPIRED_AT,
    )
    reasons = {decision.entry_id: decision.reason for decision in protected.decisions}
    replay_entry = catalog.get_by_ref(
        tenant_id=TENANT_ID,
        ref=replay_record.ref,
    )
    assert reasons[evidence_entry.entry_id] is (
        ArtifactCatalogGcReason.REFERENCE_PROTECTED
    )
    assert reasons[replay_entry.entry_id] is ArtifactCatalogGcReason.REPLAY_REQUIRED

    for logical_reference in catalog.list_references(evidence_entry.entry_id):
        runtime.retire_reference(
            tenant_id=TENANT_ID,
            request=_retirement(logical_reference),
        )
    stale_plan = runtime.prepare_gc(
        tenant_id=TENANT_ID,
        observed_at=EXPIRED_AT,
    )

    late = materializer.materialize(
        _request(run_id="run-3", attempt_id="attempt-3", candidate=candidate)
    ).envelope
    stale_result = runtime.apply_gc(
        tenant_id=TENANT_ID,
        plan_checksum=stale_plan.plan_checksum,
        confirmed=True,
    )

    assert len(stale_result) == 1
    assert stale_result[0].state is GraphArtifactGcOperationState.STALE
    stored_after_stale = artifact_port.read_graph_result_artifact(
        first_record.ref,
        expected_run_id=first_record.run_id,
    )
    assert stored_after_stale["payload"]["candidate_checksum"] == (
        first_record.content_checksum
    )
    late_reference = next(
        reference
        for reference in catalog.list_references(evidence_entry.entry_id)
        if reference.owner_run_id == "run-3"
    )
    runtime.retire_reference(
        tenant_id=TENANT_ID,
        request=_retirement(late_reference),
    )
    assert late.materialized_refs[0].ref == first_record.ref

    real_lifecycle = FilesystemGraphArtifactLifecycle(
        root,
        artifact_port=artifact_port,
        clock=lambda: EXPIRED_AT + timedelta(hours=1),
    )
    crashing_runtime = GraphArtifactGovernanceRuntime(
        catalog=catalog,
        lifecycle=_CrashAfterQuarantine(real_lifecycle),
        ledger=store,
        config=config,
        clock=lambda: EXPIRED_AT + timedelta(minutes=1),
    )
    final_plan = crashing_runtime.prepare_gc(
        tenant_id=TENANT_ID,
        observed_at=EXPIRED_AT + timedelta(minutes=1),
    )
    interrupted = crashing_runtime.apply_gc(
        tenant_id=TENANT_ID,
        plan_checksum=final_plan.plan_checksum,
        confirmed=True,
    )
    assert interrupted[0].state is GraphArtifactGcOperationState.RETRYABLE_FAILURE

    restarted_store = _store(database)
    restarted_catalog = LocalJsonArtifactCatalog(catalog_root)
    restarted_lifecycle = FilesystemGraphArtifactLifecycle(
        root,
        clock=lambda: EXPIRED_AT + timedelta(hours=2),
    )
    restarted = GraphArtifactGovernanceRuntime(
        catalog=restarted_catalog,
        lifecycle=restarted_lifecycle,
        ledger=restarted_store,
        config=config,
        clock=lambda: EXPIRED_AT + timedelta(hours=2),
    )
    resumed = restarted.resume_gc(tenant_id=TENANT_ID)

    assert len(resumed) == 1
    assert resumed[0].state is GraphArtifactGcOperationState.COMPLETED
    tombstone = restarted_store.get_gc_tombstone(
        tenant_id=TENANT_ID,
        operation_id=resumed[0].operation_id,
    )
    assert tombstone is not None
    assert resumed[0].deletion is not None
    assert tombstone.deletion_receipt_checksum == (
        resumed[0].deletion.receipt_checksum
    )
    repeated = restarted.apply_gc(
        tenant_id=TENANT_ID,
        plan_checksum=final_plan.plan_checksum,
        confirmed=True,
    )
    assert repeated == resumed
    assert restarted_catalog.reconcile(
        now=EXPIRED_AT + timedelta(hours=2),
        tenant_id=TENANT_ID,
    ).is_clean
    snapshot = restarted_catalog.snapshot(
        captured_at=EXPIRED_AT + timedelta(hours=2),
        tenant_id=TENANT_ID,
    )
    assert {entry.entry_id for entry in snapshot.entries} == {
        replay_entry.entry_id
    }
    manifest = restarted_lifecycle.terminal_store.read_terminal_manifest(
        first_record.run_id
    )
    assert manifest.artifact(first_record.artifact_type) is None


def test_concurrent_multi_run_and_class_quota_has_deterministic_totals(
    tmp_path: Path,
) -> None:
    store = SQLiteGraphResultStore(
        tmp_path / "quota-scale.sqlite3",
        max_materialized_bytes_per_run=50,
        max_artifacts_per_run=5,
        max_materialized_bytes_per_tenant=1_000,
        max_artifacts_per_tenant=100,
        max_materialized_bytes_per_class=500,
        max_artifacts_per_class=50,
        clock=lambda: NOW,
    )

    def reserve_and_settle(index: int):
        artifact_class = (
            ArtifactClass.EVIDENCE
            if index % 2 == 0
            else ArtifactClass.INTERMEDIATE
        )
        reservation = store.reserve(
            tenant_id=TENANT_ID,
            run_id=f"run-{index % 20:02d}",
            graph_id="graph-quota-scale",
            node_id=f"branch-{index:03d}",
            artifact_class=artifact_class,
            retention_class=RetentionClass.RUN,
            policy_version="graph-artifact-policy@1",
            reservation_key=f"quota-scale://{index:03d}",
            requested_bytes=10,
            object_count=1,
        )
        assert reservation is not None
        store.settle(
            reservation,
            actual_bytes=10,
            object_count=1,
            outcome=ResultMaterializationOutcome.SUCCEEDED,
        )
        return reservation

    with ThreadPoolExecutor(max_workers=16) as executor:
        reservations = tuple(executor.map(reserve_and_settle, range(100)))

    snapshots = store.quota_snapshots(
        tenant_id=TENANT_ID,
        captured_at=NOW,
    )
    tenant = next(
        item for item in snapshots if item.scope is GraphArtifactQuotaScope.TENANT
    )
    runs = tuple(
        item for item in snapshots if item.scope is GraphArtifactQuotaScope.RUN
    )
    classes = tuple(
        item
        for item in snapshots
        if item.scope is GraphArtifactQuotaScope.ARTIFACT_CLASS
    )

    assert len({item.reservation_id for item in reservations}) == 100
    assert (tenant.charged_bytes, tenant.charged_objects) == (1_000, 100)
    assert (tenant.pending_bytes, tenant.pending_objects) == (0, 0)
    assert len(runs) == 20
    assert {
        (item.charged_bytes, item.charged_objects) for item in runs
    } == {(50, 5)}
    assert len(classes) == 2
    assert {
        item.artifact_class: (item.charged_bytes, item.charged_objects)
        for item in classes
    } == {
        ArtifactClass.EVIDENCE: (500, 50),
        ArtifactClass.INTERMEDIATE: (500, 50),
    }
    assert store.reserve(
        tenant_id=TENANT_ID,
        run_id="run-overflow",
        graph_id="graph-quota-scale",
        node_id="branch-overflow",
        artifact_class=ArtifactClass.EVIDENCE,
        retention_class=RetentionClass.RUN,
        policy_version="graph-artifact-policy@1",
        reservation_key="quota-scale://overflow",
        requested_bytes=1,
        object_count=1,
    ) is None


def test_hundred_branch_gc_converges_without_duplicate_delete_or_quota_orphan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "scale-runs"
    database = tmp_path / "scale-results.sqlite3"
    config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE,
        max_artifacts_per_run=100,
        max_materialized_bytes_per_run=10 * 1024 * 1024,
        max_artifacts_per_tenant=100,
        max_materialized_bytes_per_tenant=10 * 1024 * 1024,
        max_artifacts_per_class=100,
        max_materialized_bytes_per_class=10 * 1024 * 1024,
        retention=GraphArtifactRetentionSettings(
            ephemeral_days=1,
            run_days=30,
            evidence_days=180,
            report_days=None,
            cache_days=1,
        ),
    )
    artifact_port = FilesystemHarnessArtifactPort(root)
    catalog = LocalJsonArtifactCatalog(
        root / "_records" / "graph_artifact_catalog"
    )
    store = SQLiteGraphResultStore(
        database,
        max_materialized_bytes_per_run=config.max_materialized_bytes_per_run,
        max_artifacts_per_run=config.max_artifacts_per_run,
        max_materialized_bytes_per_tenant=(
            config.max_materialized_bytes_per_tenant
        ),
        max_artifacts_per_tenant=config.max_artifacts_per_tenant,
        max_materialized_bytes_per_class=(
            config.max_materialized_bytes_per_class
        ),
        max_artifacts_per_class=config.max_artifacts_per_class,
        clock=lambda: NOW,
    )
    materializer = _materializer(
        config=config,
        artifact_port=artifact_port,
        catalog=catalog,
        store=store,
    )
    records = []
    for index in range(100):
        envelope = materializer.materialize(
            _request(
                run_id="run-scale",
                attempt_id=f"attempt-{index:03d}",
                node_id=f"branch-{index:03d}",
                candidate={
                    "branch": index,
                    "data": f"branch-{index:03d}-" + "z" * (40 * 1024),
                },
                artifact_class=ArtifactClass.INTERMEDIATE,
            )
        ).envelope
        records.append(envelope.materialized_refs[0])
    _commit_terminal_manifest(artifact_port, "run-scale")

    before_rejection = catalog.snapshot(
        captured_at=NOW,
        tenant_id=TENANT_ID,
    )
    before_manifest = artifact_port.read_terminal_manifest("run-scale")
    with pytest.raises(GraphArtifactResultError) as rejected:
        materializer.materialize(
            _request(
                run_id="run-scale",
                attempt_id="attempt-overflow",
                node_id="branch-overflow",
                candidate={"data": "overflow-" + "q" * (40 * 1024)},
                artifact_class=ArtifactClass.INTERMEDIATE,
                required_for_replay=True,
            )
        )
    assert rejected.value.error_code is GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED
    after_rejection = catalog.snapshot(
        captured_at=NOW,
        tenant_id=TENANT_ID,
    )
    after_manifest = artifact_port.read_terminal_manifest("run-scale")
    assert len(before_rejection.entries) == len(after_rejection.entries) == 100
    assert len(before_rejection.claims) == len(after_rejection.claims) == 100
    assert len(before_manifest.artifacts) == 100
    assert after_manifest.artifacts == before_manifest.artifacts

    lifecycle_one = FilesystemGraphArtifactLifecycle(
        root,
        artifact_port=artifact_port,
        clock=lambda: EXPIRED_AT + timedelta(hours=1),
    )
    lifecycle_two = FilesystemGraphArtifactLifecycle(
        root,
        clock=lambda: EXPIRED_AT + timedelta(hours=1),
    )
    runtime_one = GraphArtifactGovernanceRuntime(
        catalog=catalog,
        lifecycle=lifecycle_one,
        ledger=store,
        config=config,
        clock=lambda: EXPIRED_AT,
    )
    runtime_two = GraphArtifactGovernanceRuntime(
        catalog=LocalJsonArtifactCatalog(catalog.root),
        lifecycle=lifecycle_two,
        ledger=SQLiteGraphResultStore(
            database,
            max_materialized_bytes_per_run=config.max_materialized_bytes_per_run,
            max_artifacts_per_run=config.max_artifacts_per_run,
            max_materialized_bytes_per_tenant=(
                config.max_materialized_bytes_per_tenant
            ),
            max_artifacts_per_tenant=config.max_artifacts_per_tenant,
            max_materialized_bytes_per_class=(
                config.max_materialized_bytes_per_class
            ),
            max_artifacts_per_class=config.max_artifacts_per_class,
            clock=lambda: NOW,
        ),
        config=config,
        clock=lambda: EXPIRED_AT,
    )
    plan = runtime_one.prepare_gc(
        tenant_id=TENANT_ID,
        observed_at=EXPIRED_AT,
    )
    assert sum(
        decision.action is ArtifactCatalogGcAction.DELETE_CANDIDATE
        for decision in plan.decisions
    ) == 100

    def apply(runtime: GraphArtifactGovernanceRuntime):
        return runtime.apply_gc(
            tenant_id=TENANT_ID,
            plan_checksum=plan.plan_checksum,
            confirmed=True,
            max_operations=100,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(apply, (runtime_one, runtime_two)))

    assert all(len(outcome) == 100 for outcome in outcomes)
    operations = store.list_gc_operations(
        tenant_id=TENANT_ID,
        include_completed=True,
    )
    completed = tuple(
        operation
        for operation in operations
        if operation.state is GraphArtifactGcOperationState.COMPLETED
    )
    assert len(completed) == 100
    assert all(
        store.get_gc_tombstone(
            tenant_id=TENANT_ID,
            operation_id=operation.operation_id,
        )
        is not None
        for operation in completed
    )
    final_snapshot = catalog.snapshot(
        captured_at=EXPIRED_AT + timedelta(hours=2),
        tenant_id=TENANT_ID,
    )
    assert final_snapshot.entries == ()
    assert final_snapshot.claims == ()
    assert final_snapshot.references == ()
    assert catalog.reconcile(
        now=EXPIRED_AT + timedelta(hours=2),
        tenant_id=TENANT_ID,
    ).is_clean
    final_manifest = artifact_port.read_terminal_manifest("run-scale")
    assert final_manifest.artifacts == ()
    gc_usage = tuple(
        fact
        for fact in store.list_usage(
            tenant_id=TENANT_ID,
            window_start=NOW.replace(hour=0),
            window_end=EXPIRED_AT + timedelta(days=1),
        )
        if fact.kind is GraphArtifactUsageKind.GC_TRANSITION
    )
    purged = tuple(
        fact
        for fact in gc_usage
        if fact.reason_code == GraphArtifactUsageReason.GC_PURGED.value
    )
    assert len(purged) == 100
    assert sum(fact.object_count for fact in purged) == 100
    assert sum(fact.physical_bytes for fact in purged) == sum(
        record.byte_size for record in records
    )


def test_governance_serialization_never_contains_raw_artifact_content(
    tmp_path: Path,
) -> None:
    secret = "sk-live-graph-artifact-secret-marker"
    private_marker = "customer-private-path-marker"
    private_path = rf"C:\{private_marker}\payload.json"
    raw_tool_payload = "RAW_TOOL_BODY_marker:{authorization=Bearer-secret}"
    root = tmp_path / "privacy-runs"
    config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE,
        max_artifacts_per_run=10,
        max_materialized_bytes_per_run=100 * 1024,
        max_artifacts_per_tenant=10,
        max_materialized_bytes_per_tenant=100 * 1024,
        max_artifacts_per_class=10,
        max_materialized_bytes_per_class=100 * 1024,
        quota_alert_threshold_basis_points=1,
        gc_backlog_alert_bytes=1,
        retention=GraphArtifactRetentionSettings(
            ephemeral_days=1,
            run_days=30,
            evidence_days=180,
            report_days=None,
            cache_days=1,
        ),
    )
    artifact_port = FilesystemHarnessArtifactPort(root)
    catalog = LocalJsonArtifactCatalog(
        root / "_records" / "graph_artifact_catalog"
    )
    store = _store(tmp_path / "privacy-results.sqlite3")
    materializer = _materializer(
        config=config,
        artifact_port=artifact_port,
        catalog=catalog,
        store=store,
    )
    runtime = GraphArtifactGovernanceRuntime(
        catalog=catalog,
        lifecycle=FilesystemGraphArtifactLifecycle(
            root,
            artifact_port=artifact_port,
            clock=lambda: EXPIRED_AT,
        ),
        ledger=store,
        config=config,
        clock=lambda: EXPIRED_AT,
    )
    request = _request(
        run_id="run-privacy",
        attempt_id="attempt-privacy",
        candidate={
            "opaque_text": secret,
            "source_hint": private_path,
            "worker_output": raw_tool_payload,
            "padding": "p" * (40 * 1024),
        },
        artifact_class=ArtifactClass.INTERMEDIATE,
    )

    envelope = materializer.materialize(request).envelope
    record = envelope.materialized_refs[0]
    stored_body = artifact_port.read_graph_result_artifact(
        record.ref,
        expected_run_id=record.run_id,
    )
    stored_text = json.dumps(stored_body, ensure_ascii=False, sort_keys=True)
    assert secret in stored_text
    assert private_marker in stored_text
    assert raw_tool_payload in stored_text

    plan = runtime.prepare_gc(
        tenant_id=TENANT_ID,
        observed_at=EXPIRED_AT,
    )
    report = runtime.generate_cost_report(
        tenant_id=TENANT_ID,
        window_start=NOW.replace(hour=0, minute=0, second=0, microsecond=0),
        generated_at=EXPIRED_AT,
    )
    alerts = runtime.evaluate_alerts(
        tenant_id=TENANT_ID,
        report=report,
        gc_plan=plan,
    )
    secret_request = replace(
        _request(
            run_id="run-secret-rejected",
            attempt_id="attempt-secret-rejected",
            candidate={
                "opaque_text": secret,
                "source_hint": private_path,
                "worker_output": raw_tool_payload,
            },
            artifact_class=ArtifactClass.INTERMEDIATE,
        ),
        sensitivity=ResultSensitivity.SECRET,
    )
    with pytest.raises(GraphArtifactResultError) as rejected:
        materializer.materialize(secret_request)

    usage = store.list_usage(
        tenant_id=TENANT_ID,
        window_start=NOW.replace(hour=0, minute=0, second=0, microsecond=0),
        window_end=EXPIRED_AT + timedelta(days=1),
    )
    operations = store.list_gc_operations(
        tenant_id=TENANT_ID,
        include_completed=True,
    )
    governance_text = json.dumps(
        {
            "usage": [fact.to_dict() for fact in usage],
            "report": report.to_dict(),
            "alerts": [alert.to_dict() for alert in alerts],
            "operations": [operation.to_dict() for operation in operations],
            "error": rejected.value.to_event_payload(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert alerts
    assert operations
    assert rejected.value.error_code is (
        GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED
    )
    assert secret not in governance_text
    assert private_marker not in governance_text
    assert raw_tool_payload not in governance_text


def _config() -> GraphArtifactPersistenceConfig:
    return GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE,
        retention=GraphArtifactRetentionSettings(
            ephemeral_days=1,
            run_days=30,
            evidence_days=180,
            report_days=None,
            cache_days=1,
        )
    )


def _store(path: Path) -> SQLiteGraphResultStore:
    return SQLiteGraphResultStore(path, clock=lambda: NOW)


def _materializer(
    *,
    config: GraphArtifactPersistenceConfig,
    artifact_port: FilesystemHarnessArtifactPort,
    catalog: LocalJsonArtifactCatalog,
    store: SQLiteGraphResultStore,
) -> ResultMaterializer:
    return ResultMaterializer(
        policy=PersistencePolicy(config),
        artifact_port=artifact_port,
        catalog=catalog,
        quota=store,
        usage=store,
        cache=store,
        attempts=store,
        clock=lambda: NOW,
    )


def _commit_terminal_manifest(
    artifact_port: FilesystemHarnessArtifactPort,
    run_id: str,
) -> None:
    artifacts = artifact_port.list_staged_artifacts(run_id)
    assert artifacts
    artifact_port.write_terminal_manifest(
        GraphTerminalManifest(
            tenant_id=TENANT_ID,
            run_id=run_id,
            graph_id="research-governance-e2e",
            graph_version="1.0.0",
            graph_schema_version="1.0.0",
            compiler_version="1.0.0",
            normalized_graph_checksum=checksum_for({"graph": run_id}),
            status="succeeded",
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            terminal_state_ref=checksum_for({"state": run_id}),
            checkpoint_ref=f"graph-state://{run_id}/terminal",
            terminal_node_ids=("branch-result",),
            gate_evidence_refs=(checksum_for({"gate": run_id}),),
            artifacts=artifacts,
        )
    )


def _request(
    *,
    run_id: str,
    attempt_id: str,
    candidate: dict,
    node_id: str = "branch-result",
    artifact_class: ArtifactClass = ArtifactClass.EVIDENCE,
    required_for_replay: bool = False,
) -> NodeResultRequest:
    return NodeResultRequest(
        binding=NodeResultBinding(
            tenant_id=TENANT_ID,
            tenant_scope_ref=TENANT_SCOPE,
            run_id=run_id,
            graph_id="graph-e2e",
            graph_version="graph-e2e@1",
            node_id=node_id,
            attempt_id=attempt_id,
            parent_checkpoint_ref=f"checkpoint://{run_id}/1",
        ),
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="research-result@1",
        output_schema_digest="sha256:" + "a" * 64,
        candidate=candidate,
        media_type="application/json",
        summary=BoundedSummary.from_text("bounded branch result"),
        inline_projection={"count": 1},
        inline_allowed_fields=("count",),
        provenance=ResultProvenance(
            producer_ref="research-worker@1",
            producer_revision="research-worker-revision@1",
        ),
        artifact_class=artifact_class,
        retention_class=RetentionClass.EPHEMERAL,
        sensitivity=ResultSensitivity.INTERNAL,
        required_for_replay=required_for_replay,
        required_for_publication=False,
        reusable=False,
        side_effect_free=True,
        dependency_digest=None,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        created_at=NOW,
    )


def _retirement(reference) -> ArtifactReferenceRetirementRequest:
    authorization = ArtifactLifecycleAuthorization.create(
        kind=ArtifactLifecycleAuthorityKind.TERMINAL_RUN,
        tenant_id=reference.tenant_id,
        owner_run_id=reference.owner_run_id,
        owner_id=reference.owner_id,
        lifecycle_ref=(
            f"run-lifecycle://{reference.owner_run_id}/terminal"
        ),
        observed_at=EXPIRED_AT,
        policy_version="graph-artifact-policy@1",
    )
    return ArtifactReferenceRetirementRequest.create(
        reference=reference,
        authorization=authorization,
        reason=ArtifactReferenceRetirementReason.RETENTION_EXPIRED,
        requested_at=EXPIRED_AT,
    )
