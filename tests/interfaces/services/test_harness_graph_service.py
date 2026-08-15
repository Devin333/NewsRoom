from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.graph_observability import (
    graph_health_report,
    graph_metric_samples,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.graph.dsl import HarnessGraphSpec, StepRef
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workers.result import HarnessWorkerResult
from interfaces.models.actor import ActorContext
from interfaces.services.harness_graph_service import (
    HarnessGraphActorScope,
    HarnessGraphApplicationService,
    HarnessGraphAuthorizationError,
    HarnessGraphNotFoundError,
    HarnessGraphRequestError,
    HarnessGraphRuntimeBinding,
)


_NOW = datetime(2026, 7, 31, tzinfo=UTC)
_TENANT_REF = checksum_for("tenant-inspection")
_IDENTITY_REF = checksum_for("identity-inspection")
_ACTOR_REF = checksum_for("actor-inspection")


class _Dispatcher:
    def __init__(self) -> None:
        self.activities: list[HarnessGraphActivity] = []
        self.cancellations: list[object] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.activities.append(activity)

    def request_cancellation(self, request: object) -> None:
        self.cancellations.append(request)


class _RuntimeResolver:
    def __init__(self, binding: HarnessGraphRuntimeBinding) -> None:
        self.binding = binding

    def resolve(self, run_id: str, *, actor: ActorContext) -> HarnessGraphRuntimeBinding:
        assert actor.actor_id
        assert run_id == self.binding.run_spec.run_id
        return self.binding


class _ScopeResolver:
    def __init__(self, scope: HarnessGraphActorScope) -> None:
        self.scope = scope

    def resolve(self, actor: ActorContext) -> HarnessGraphActorScope:
        assert actor.actor_id
        return self.scope


def test_graph_inspection_is_scope_bound_and_excludes_raw_payloads() -> None:
    service, control_plane, run_spec = _service("run-graph-inspection")

    result = service.inspect_run(run_spec.run_id, verify_history=True)
    payload = result.to_dict()

    assert payload["lifecycle"] == "completed"
    assert payload["outcome"] == "succeeded"
    assert payload["counts"]["terminal"] == 1
    assert payload["replay"]["pending_cause_count"] == 0
    assert payload["projection_checksum"] == (
        control_plane.recover_graph(run_spec).projection_checksum
    )
    serialized = str(payload)
    assert "raw-secret-value" not in serialized
    assert "raw prompt" not in serialized
    assert _TENANT_REF not in serialized
    assert _IDENTITY_REF not in serialized


def test_graph_metrics_use_only_low_cardinality_labels() -> None:
    _, control_plane, run_spec = _service("run-graph-metrics")
    state = control_plane.recover_graph(run_spec)

    samples = graph_metric_samples(
        state,
        decision_latency_ms=1.25,
        replay_mismatch=True,
    )

    assert {sample.name for sample in samples} >= {
        "harness_graph_active_nodes",
        "harness_graph_ready_nodes",
        "harness_graph_wait_age_sequences",
        "harness_graph_compensation_completed",
        "harness_graph_decision_latency_ms",
        "harness_graph_replay_mismatch",
    }
    assert all(set(sample.labels) <= {"lifecycle", "outcome", "result"} for sample in samples)
    assert all(run_spec.run_id not in sample.labels.values() for sample in samples)


def test_graph_health_reports_lag_and_incompatible_history_without_payloads() -> None:
    _, control_plane, run_spec = _service("run-graph-health")
    state = control_plane.recover_graph(run_spec)

    degraded = graph_health_report(
        state,
        canonical_high_watermark=state.last_event_sequence + 101,
    )
    unhealthy = graph_health_report(state, incompatible_history=True)

    assert degraded.status.value == "degraded"
    assert degraded.diagnostics[0].code == "event_projection_lag"
    assert unhealthy.status.value == "unhealthy"
    assert unhealthy.diagnostics[0].code == "incompatible_history"
    assert "raw-secret-value" not in str(unhealthy.to_dict())


def test_graph_service_hides_scope_mismatch_and_denies_missing_permission() -> None:
    service, _, run_spec = _service(
        "run-graph-scope-mismatch",
        actor_scope=HarnessGraphActorScope(
            checksum_for("another-tenant"),
            _IDENTITY_REF,
            _ACTOR_REF,
        ),
    )
    denied, _, denied_spec = _service(
        "run-graph-denied",
        actor=ActorContext(
            actor_id="actor-denied",
            actor_type="user",
            roles=[],
            request_id="request-denied",
        ),
    )

    with pytest.raises(HarnessGraphNotFoundError) as hidden:
        service.inspect_run(run_spec.run_id)
    with pytest.raises(HarnessGraphAuthorizationError) as forbidden:
        denied.inspect_run(denied_spec.run_id)

    assert hidden.value.code == "graph_run_not_found"
    assert forbidden.value.code == "graph_inspection_permission_denied"


def test_graph_service_exposes_safe_verified_replay_projection() -> None:
    service, _, run_spec = _service("run-graph-replay")

    result = service.replay_run(run_spec.run_id)
    payload = result.to_dict()

    assert payload["status"] == "verified"
    assert payload["through_sequence"] > 0
    assert payload["projection_checksum"].startswith("sha256:")
    assert payload["quarantine_reason"] is None
    assert "raw-secret-value" not in str(payload)
    with pytest.raises(HarnessGraphRequestError) as invalid:
        service.replay_run(run_spec.run_id, through_sequence=0)
    assert invalid.value.code == "graph_replay_sequence_invalid"


def test_graph_service_submits_cancel_to_harness_after_scope_authorization() -> None:
    dispatcher = _Dispatcher()
    service, control_plane, run_spec = _service(
        "run-graph-cancel",
        actor=ActorContext(
            actor_id="operator-1",
            actor_type="user",
            roles=["operator"],
            request_id="request-run-graph-cancel",
        ),
        dispatcher=dispatcher,
    )

    result = service.cancel_run(
        run_spec.run_id,
        cancellation_id="cancel-service-1",
        reason_code="operator_cancelled",
    )
    payload = result.to_dict()

    assert payload["operation"] == "cancel"
    assert payload["operation_id"] == "cancel-service-1"
    assert payload["operation_ref"].startswith("sha256:")
    assert payload["run"]["lifecycle"] == "running"
    assert payload["run"]["node_instances"][0]["status"] == "cancel_requested"
    assert len(dispatcher.cancellations) == 1
    recovery = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert len(recovery.observation_commits) >= 1
    assert "operator-1" not in str(payload)


def test_graph_cancel_requires_write_permission_before_runtime_mutation() -> None:
    dispatcher = _Dispatcher()
    service, control_plane, run_spec = _service(
        "run-graph-cancel-denied",
        dispatcher=dispatcher,
    )
    before = control_plane.graph_transition_port.recover_graph(run_spec.run_id)

    with pytest.raises(HarnessGraphAuthorizationError) as captured:
        service.cancel_run(
            run_spec.run_id,
            cancellation_id="cancel-denied",
            reason_code="operator_cancelled",
        )

    after = control_plane.graph_transition_port.recover_graph(run_spec.run_id)
    assert captured.value.code == "graph_run_operation_permission_denied"
    assert after == before
    assert dispatcher.cancellations == []


def _service(
    run_id: str,
    *,
    actor: ActorContext | None = None,
    actor_scope: HarnessGraphActorScope | None = None,
    dispatcher: _Dispatcher | None = None,
) -> tuple[HarnessGraphApplicationService, HarnessControlPlane, HarnessRunSpec]:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(HarnessStepSpec("inspect", "script", output_key="result"),),
        entry_step_id="inspect",
        graph=HarnessGraphSpec(f"graph-{run_id}", StepRef("inspect")),
    )
    run_spec = HarnessRunSpec(
        run_id,
        workflow,
        metadata={
            "tenant_scope_ref": _TENANT_REF,
            "identity_scope_ref": _IDENTITY_REF,
            "secret": "raw-secret-value",
            "prompt": "raw prompt",
        },
        created_at=_NOW,
    )
    control_plane = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "inspect": lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"secret": "raw-secret-value"},
            )
        },
        graph_activity_dispatcher=dispatcher,
    )
    control_plane.run(run_spec)
    binding = HarnessGraphRuntimeBinding(run_spec, control_plane)
    service = HarnessGraphApplicationService(
        actor=(
            actor
            or ActorContext(
                actor_id="actor-1",
                actor_type="user",
                roles=["viewer"],
                request_id=f"request-{run_id}",
            )
        ),
        runtime_resolver=_RuntimeResolver(binding),
        actor_scope_resolver=_ScopeResolver(
            actor_scope
            if actor_scope is not None
            else HarnessGraphActorScope(_TENANT_REF, _IDENTITY_REF, _ACTOR_REF)
        ),
        clock=lambda: _NOW,
    )
    return service, control_plane, run_spec
