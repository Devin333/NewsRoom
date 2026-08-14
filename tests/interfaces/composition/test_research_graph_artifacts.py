from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    GraphArtifactAlert,
    GraphArtifactAlertKind,
    GraphArtifactAlertReason,
    GraphArtifactAlertStatus,
)
from framework.harness.artifacts.catalog import ArtifactCatalogRegistrationRequest
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    BoundedSummary,
    ContextPolicy,
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    GraphArtifactRolloutMode,
    NodeResultBinding,
    NodeResultRequest,
    NodeResultStatus,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from interfaces.composition.research_graph_artifacts import (
    compose_research_graph_artifact_runtime,
)
from interfaces.composition.research_settings import ResearchRuntimeSettings


NOW = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


def _settings(
    tmp_path,
    *,
    mode: str,
    policy_version: str = "graph-artifact-policy@1",
    readable_policy_versions: tuple[str, ...] = ("graph-artifact-policy@1",),
) -> ResearchRuntimeSettings:
    return ResearchRuntimeSettings.from_env(
        {
            "DASHSCOPE_API_KEY": "sk-explicit-test-only",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MODE": mode,
            "NEWS_RESEARCH_GRAPH_ARTIFACT_POLICY_VERSION": policy_version,
            "NEWS_RESEARCH_GRAPH_ARTIFACT_READABLE_POLICY_VERSIONS": ",".join(
                readable_policy_versions
            ),
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_PER_RUN": "11",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_MATERIALIZED_BYTES_PER_RUN": "11000",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_PER_TENANT": "22",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_MATERIALIZED_BYTES_PER_TENANT": "22000",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_PER_CLASS": "12",
            "NEWS_RESEARCH_GRAPH_ARTIFACT_MAX_MATERIALIZED_BYTES_PER_CLASS": "12000",
        },
        cwd=tmp_path,
    )


def _materialization_request(
    *,
    attempt_id: str = "attempt-rollback",
) -> NodeResultRequest:
    tenant_id = "tenant-rollback"
    return NodeResultRequest(
        binding=NodeResultBinding(
            tenant_id=tenant_id,
            tenant_scope_ref=checksum_for(tenant_id),
            run_id="run-rollback",
            graph_id="research-graph",
            graph_version="research-graph@1",
            node_id="build-evidence",
            attempt_id=attempt_id,
            parent_checkpoint_ref="checkpoint://run-rollback/1",
        ),
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="research-result@1",
        output_schema_digest="sha256:" + "a" * 64,
        candidate={"data": "rollback-evidence-" + "x" * 4_096},
        media_type="application/json",
        summary=BoundedSummary.from_text("bounded rollback evidence"),
        inline_projection={"count": 1},
        inline_allowed_fields=("count",),
        provenance=ResultProvenance(
            producer_ref="research-worker@1",
            producer_revision="research-worker-revision@1",
        ),
        artifact_class=ArtifactClass.EVIDENCE,
        retention_class=RetentionClass.EVIDENCE,
        sensitivity=ResultSensitivity.INTERNAL,
        required_for_replay=False,
        required_for_publication=False,
        reusable=False,
        side_effect_free=True,
        dependency_digest=None,
        context_policy=ContextPolicy.SUMMARY_ONLY,
        created_at=NOW,
    )


@pytest.mark.parametrize(
    "mode",
    ["legacy", "shadow", "enforce", "read_only"],
)
def test_components_share_one_real_catalog_store_and_artifact_port(
    tmp_path,
    mode: str,
) -> None:
    settings = _settings(tmp_path, mode=mode)

    components = compose_research_graph_artifact_runtime(settings)

    materializer = components.materializer
    runtime = components.governance_runtime
    assert components.lifecycle.artifact_port is components.artifact_port
    assert materializer._artifact_port is components.artifact_port
    assert materializer._catalog is components.catalog
    assert materializer._quota is components.store
    assert materializer._usage is components.store
    assert materializer._cache is components.store
    assert materializer._attempts is components.store
    assert runtime._catalog is components.catalog
    assert runtime._ledger is components.store
    assert runtime._lifecycle is components.lifecycle
    assert components.governance_service.runtime is runtime
    assert components.store.max_artifacts_per_run == 11
    assert components.store.max_materialized_bytes_per_run == 11_000
    assert components.store.max_artifacts_per_tenant == 22
    assert components.store.max_materialized_bytes_per_tenant == 22_000
    assert components.store.max_artifacts_per_class == 12
    assert components.store.max_materialized_bytes_per_class == 12_000


@pytest.mark.parametrize(
    "mode",
    ["legacy", "shadow", "enforce", "read_only"],
)
def test_gc_plan_persists_only_in_enforce_mode(tmp_path, mode: str) -> None:
    components = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode=mode)
    )

    plan = components.governance_service.plan_gc(
        tenant_id="tenant-operator",
        observed_at=NOW,
    )

    stored = components.store.get_gc_plan(
        tenant_id="tenant-operator",
        plan_checksum=plan.plan_checksum,
    )
    if mode == "enforce":
        assert stored == plan
    else:
        assert stored is None
        with pytest.raises(GraphArtifactResultError) as exc_info:
            components.governance_service.apply_gc(
                tenant_id="tenant-operator",
                plan_checksum=plan.plan_checksum,
                confirmed=True,
                max_operations=1,
            )
        assert exc_info.value.error_code is (
            GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID
        )
        assert components.store.list_gc_operations(
            tenant_id="tenant-operator",
            include_completed=True,
        ) == ()


@pytest.mark.parametrize(
    ("mode", "stored"),
    [
        ("legacy", False),
        ("shadow", True),
        ("enforce", True),
        ("read_only", True),
    ],
)
def test_cost_report_is_inspectable_without_legacy_state_writes(
    tmp_path,
    mode: str,
    stored: bool,
) -> None:
    components = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode=mode)
    )

    report = components.governance_service.generate_cost_report(
        tenant_id="tenant-report",
        day=NOW.date(),
        generated_at=NOW,
    )

    assert report.tenant_id == "tenant-report"
    assert (
        components.store.get_cost_report(
            tenant_id="tenant-report",
            report_id=report.report_id,
        )
        == (report if stored else None)
    )


def test_alert_acknowledgement_is_scoped_not_found_across_tenants(tmp_path) -> None:
    components = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode="enforce")
    )
    alert = GraphArtifactAlert.create(
        kind=GraphArtifactAlertKind.CATALOG_DRIFT,
        status=GraphArtifactAlertStatus.OPEN,
        tenant_id="tenant-owner",
        scope_ref="catalog-issue://" + "a" * 64,
        policy_version="graph-artifact-policy@1",
        window_start=NOW,
        window_end=NOW + timedelta(days=1),
        observed_value=1,
        limit_value=0,
        reason_code=GraphArtifactAlertReason.CATALOG_DRIFT.value,
        created_at=NOW,
        acknowledged_at=None,
        acknowledged_by=None,
    )
    components.store.put_alert(alert)

    with pytest.raises(GraphArtifactResultError) as exc_info:
        components.governance_service.acknowledge_alert(
            tenant_id="tenant-other",
            alert_id=alert.alert_id,
            expected_checksum=alert.alert_checksum,
            acknowledged_by="operator-1",
            acknowledged_at=NOW + timedelta(minutes=1),
        )

    error = exc_info.value
    assert error.error_code is GraphArtifactResultErrorCode.GOVERNANCE_RECORD_NOT_FOUND
    assert "tenant-owner" not in json.dumps(error.to_event_payload())
    assert components.store.get_alert(
        tenant_id="tenant-owner",
        alert_id=alert.alert_id,
    ) == alert


def test_application_service_returns_exact_checked_operator_schemas(tmp_path) -> None:
    components = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode="enforce")
    )
    service = components.governance_service

    plan = service.plan_gc(tenant_id="tenant-schema", observed_at=NOW)
    applied = service.apply_gc(
        tenant_id="tenant-schema",
        plan_checksum=plan.plan_checksum,
        confirmed=True,
        max_operations=3,
    ).to_dict()
    quota = service.inspect_quota(
        tenant_id="tenant-schema",
        captured_at=NOW,
    ).to_dict()
    reconciled = service.reconcile(
        tenant_id="tenant-schema",
        observed_at=NOW,
    ).to_dict()
    alerts = service.list_alerts(tenant_id="tenant-schema").to_dict()

    assert set(applied) == {
        "tenant_id",
        "plan_checksum",
        "operations",
        "result_checksum",
    }
    assert set(quota) == {
        "tenant_id",
        "captured_at",
        "snapshots",
        "result_checksum",
    }
    assert set(reconciled) == {
        "tenant_id",
        "plan",
        "result_checksum",
    }
    assert set(alerts) == {
        "tenant_id",
        "status",
        "alerts",
        "result_checksum",
    }
    assert applied["operations"] == []
    assert len(quota["snapshots"]) == 1
    assert reconciled["plan"]["issues"] == []
    assert alerts["alerts"] == []


def test_reconciliation_records_idempotent_drift_alert_and_usage(tmp_path) -> None:
    components = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode="enforce")
    )
    record = ArtifactRecord(
        ref="artifact://run-drift/node_result_drift",
        artifact_id="node_result_drift",
        artifact_type="node_result",
        content_checksum="sha256:" + "d" * 64,
        byte_size=17,
        media_type="application/json",
        artifact_class=ArtifactClass.EVIDENCE,
        tenant_id="tenant-drift",
        run_id="run-drift",
        graph_id="research-graph",
        node_id="collect-evidence",
        attempt_id="attempt-drift",
        producer_revision="research-worker@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.EVIDENCE,
        expires_at=NOW + timedelta(days=1),
        required_for_replay=False,
        required_for_publication=False,
        created_at=NOW,
    )
    components.catalog.register(
        ArtifactCatalogRegistrationRequest.from_verified_record(
            record,
            verified_at=NOW,
        )
    )
    state_path = components.catalog.root / "catalog.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["claims"] = []
    state["references"] = []
    unsigned = {
        key: value for key, value in state.items() if key != "state_checksum"
    }
    state["state_checksum"] = checksum_for(unsigned)
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    first = components.governance_service.reconcile(
        tenant_id="tenant-drift",
        observed_at=NOW,
    )
    second = components.governance_service.reconcile(
        tenant_id="tenant-drift",
        observed_at=NOW + timedelta(minutes=1),
    )

    assert first.plan.is_clean is False
    assert second.plan.is_clean is False
    alerts = components.governance_service.list_alerts(
        tenant_id="tenant-drift"
    ).alerts
    usage = components.store.list_usage(
        tenant_id="tenant-drift",
        window_start=NOW.replace(hour=0),
        window_end=NOW.replace(hour=0) + timedelta(days=1),
    )
    assert len(alerts) == 1
    assert alerts[0].kind is GraphArtifactAlertKind.CATALOG_DRIFT
    assert len(usage) == 1
    assert components.governance_runtime.config.mode is GraphArtifactRolloutMode.ENFORCE


def test_read_only_rollback_reads_previous_policy_and_rejects_mutations(
    tmp_path,
) -> None:
    request = _materialization_request()
    enforced = compose_research_graph_artifact_runtime(
        _settings(tmp_path, mode="enforce")
    )
    committed = enforced.materializer.materialize(request).envelope
    record = committed.materialized_refs[0]
    assert committed.persistence_decision.policy_version == (
        "graph-artifact-policy@1"
    )

    read_only = compose_research_graph_artifact_runtime(
        _settings(
            tmp_path,
            mode="read_only",
            policy_version="graph-artifact-policy@2",
            readable_policy_versions=(
                "graph-artifact-policy@1",
                "graph-artifact-policy@2",
            ),
        )
    )
    recovered = read_only.materializer.require_existing(request)
    stored = read_only.artifact_port.read_graph_result_artifact(
        record.ref,
        expected_run_id=record.run_id,
    )
    plan = read_only.governance_service.plan_gc(
        tenant_id=request.binding.tenant_id,
        observed_at=NOW,
    )
    report = read_only.governance_service.generate_cost_report(
        tenant_id=request.binding.tenant_id,
        day=NOW.date(),
        generated_at=NOW + timedelta(days=1, seconds=1),
    )
    quota = read_only.governance_service.inspect_quota(
        tenant_id=request.binding.tenant_id,
        captured_at=NOW + timedelta(days=1),
    )
    reconciliation = read_only.governance_service.reconcile(
        tenant_id=request.binding.tenant_id,
        observed_at=NOW + timedelta(days=1),
    )

    assert recovered == committed
    assert stored["payload"]["candidate_checksum"] == record.content_checksum
    assert report.policy_version == "graph-artifact-policy@2"
    assert quota.snapshots
    assert reconciliation.plan.is_clean
    assert read_only.store.get_gc_plan(
        tenant_id=request.binding.tenant_id,
        plan_checksum=plan.plan_checksum,
    ) is None

    catalog_before = read_only.catalog.snapshot(
        captured_at=NOW + timedelta(days=1),
        tenant_id=request.binding.tenant_id,
    )
    staging_before = read_only.artifact_port.list_staged_artifacts(
        request.binding.run_id
    )
    usage_before = read_only.store.list_usage(
        tenant_id=request.binding.tenant_id,
        window_start=NOW - timedelta(days=1),
        window_end=NOW + timedelta(days=3),
    )
    operations_before = read_only.store.list_gc_operations(
        tenant_id=request.binding.tenant_id,
        include_completed=True,
    )
    missing = replace(
        request,
        binding=replace(request.binding, attempt_id="attempt-missing"),
    )

    with pytest.raises(GraphArtifactResultError) as missing_attempt:
        read_only.materializer.require_existing(missing)
    with pytest.raises(GraphArtifactResultError) as gc_apply:
        read_only.governance_service.apply_gc(
            tenant_id=request.binding.tenant_id,
            plan_checksum=plan.plan_checksum,
            confirmed=True,
            max_operations=1,
        )

    assert missing_attempt.value.error_code is (
        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED
    )
    assert gc_apply.value.error_code is (
        GraphArtifactResultErrorCode.LIFECYCLE_AUTHORIZATION_INVALID
    )
    assert read_only.materializer.recover(missing.binding) is None
    assert read_only.catalog.snapshot(
        captured_at=NOW + timedelta(days=1),
        tenant_id=request.binding.tenant_id,
    ) == catalog_before
    assert read_only.artifact_port.list_staged_artifacts(
        request.binding.run_id
    ) == staging_before
    assert read_only.store.list_usage(
        tenant_id=request.binding.tenant_id,
        window_start=NOW - timedelta(days=1),
        window_end=NOW + timedelta(days=3),
    ) == usage_before
    assert read_only.store.list_gc_operations(
        tenant_id=request.binding.tenant_id,
        include_completed=True,
    ) == operations_before

    incompatible_reader = compose_research_graph_artifact_runtime(
        _settings(
            tmp_path,
            mode="read_only",
            policy_version="graph-artifact-policy@2",
            readable_policy_versions=("graph-artifact-policy@2",),
        )
    )
    with pytest.raises(GraphArtifactResultError) as unsupported:
        incompatible_reader.materializer.require_existing(request)
    assert unsupported.value.error_code is (
        GraphArtifactResultErrorCode.POLICY_VERSION_UNSUPPORTED
    )
    assert incompatible_reader.materializer.recover(request.binding) == committed
