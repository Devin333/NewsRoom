from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import canonical_json_bytes, checksum_for
from framework.events.errors import EventReplayMismatchError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.durable_events import (
    _graph_activity_result_from_dict,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_runtime import HarnessGraphCommitKind
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.control_plane.transition import run_spec_checksum
from framework.harness.runtime import (
    ArtifactClass,
    ArtifactRecord,
    BoundedSummary,
    ContextPolicy,
    HarnessGraphResultRuntime,
    NodeResultEnvelope,
    NodeResultStatus,
    PersistenceDecision,
    PersistenceMode,
    PersistenceReason,
    ResultMetrics,
    ResultProvenance,
    ResultSensitivity,
    RetentionClass,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.canonical import thaw_json
from framework.harness.graph.definition import HarnessGraphDefinition, HarnessGraphLeafBinding
from framework.harness.graph.dsl import (
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
)
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.side_effects.fake import (
    CountingHarnessSideEffectHandler,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.side_effects.registry import (
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectRegistry,
)
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.graph.validation import HarnessGraphPreflightPolicy
from framework.harness.graph.validation import HarnessGraphPreflight
from framework.harness.workers.result import HarnessWorkerResult
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
TENANT_ID = "tenant-1"
TENANT_SCOPE_REF = checksum_for(TENANT_ID)
SUBJECT_SCOPE_REF = checksum_for("subject-1")
SCHEMA_DIGEST = checksum_for("graph-result-schema@1")


class RecordingDispatcher:
    def __init__(self) -> None:
        self.activities = []
        self.cancellation_requests = []

    def dispatch(self, activity) -> None:
        self.activities.append(activity)

    def concurrency_capabilities_for(self, _activity_ref):
        return HarnessActivityCapabilities(
            termination_confirmation=True,
            stable_idempotency=True,
            fencing=True,
            reconciliation=True,
        )

    def request_cancellation(self, request) -> None:
        self.cancellation_requests.append(request)


class _ExternalWorker:
    worker_version = "1"
    worker_type = "function"

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id

    def execute(self, _task):
        raise AssertionError("external materialized result path must not call a worker")


class _ParallelSafeActivity:
    activity_contract_id = "newsroom.harness-worker-activity"
    activity_contract_version = "v1"
    capabilities = HarnessActivityCapabilities(
        termination_confirmation=True,
        stable_idempotency=True,
        fencing=True,
        reconciliation=True,
    )

    def dispatch(self, _request) -> None:
        raise AssertionError("external dispatcher owns activity dispatch")


class FailResultProjectionPort(InMemoryHarnessEventPort):
    def __init__(self) -> None:
        super().__init__()
        self.fail_result_projection = False

    def commit_graph_projection(self, commit, **kwargs):
        if (
            self.fail_result_projection
            and commit.commit_kind is HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION
        ):
            self.fail_result_projection = False
            raise RuntimeError("result projection unavailable")
        return super().commit_graph_projection(commit, **kwargs)


def test_materialized_result_projects_only_bounded_control_lineage() -> None:
    fixture = _dispatched("run-inline-result")
    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    envelope = _envelope(binding)

    state = fixture.adapter.accept_materialized_result(
        envelope,
        expected_binding=binding,
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=1),
        context_fingerprint=checksum_for("context-1"),
    )

    node = next(item for item in state.node_instances if item.instance_id == fixture.activity.node_instance_id)
    projection = node.output_refs["activity_result_lineage"]
    assert projection["attempt_id"] == "physical-attempt-1"
    assert projection["inline_projection"] == {"count": 1}
    assert projection["policy_version"] == "graph-artifact-policy@1"
    assert projection["context_fingerprint"] == checksum_for("context-1")
    assert node.output_refs["activity_result"] == projection["envelope_checksum"]
    assert node.metadata["activity_result_lineage_ref"] == projection["lineage_checksum"]
    recovery = fixture.port.recover_graph(binding.run_id)
    cause = recovery.activity_result_commits[-1]
    projected = recovery.projection_commits[-1]
    assert cause.result.result_lineage is not None
    assert cause.result.result_lineage.control_projection() == thaw_json(projection)
    assert (
        type(cause.result.result_lineage).from_dict(
            cause.result.result_lineage.to_dict()
        )
        == cause.result.result_lineage
    )
    assert _graph_activity_result_from_dict(cause.result.to_dict()) == cause.result
    assert projected.cause_checksum == cause.result.result_checksum
    assert projected.sequence == cause.sequence + 1


def test_duplicate_is_idempotent_and_conflicting_candidate_is_rejected() -> None:
    fixture = _dispatched("run-result-idempotency")
    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    envelope = _envelope(binding)
    accepted = fixture.adapter.accept_materialized_result(
        envelope,
        expected_binding=binding,
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=1),
    )

    duplicate = fixture.adapter.accept_materialized_result(
        envelope,
        expected_binding=binding,
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=2),
    )
    conflicting = replace(
        envelope,
        candidate_checksum=checksum_for("different-candidate"),
    )
    with pytest.raises(EventReplayMismatchError, match="conflicting duplicate"):
        fixture.adapter.accept_materialized_result(
            conflicting,
            expected_binding=binding,
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=3),
        )

    assert duplicate == accepted
    recovery = fixture.port.recover_graph(binding.run_id)
    assert len(recovery.activity_result_commits) == 1


def test_pending_result_cause_recovers_without_another_dispatch() -> None:
    port = FailResultProjectionPort()
    fixture = _dispatched("run-result-recovery", port=port)
    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    envelope = _envelope(binding)
    port.fail_result_projection = True

    with pytest.raises(RuntimeError, match="result projection unavailable"):
        fixture.adapter.accept_materialized_result(
            envelope,
            expected_binding=binding,
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )

    interrupted = port.recover_graph(binding.run_id)
    assert len(interrupted.pending_activity_results) == 1
    dispatch_count = len(fixture.dispatcher.activities)
    recovered = HarnessGraphControlPlaneRuntime(port).recover(
        binding.run_id,
        fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
    )
    assert len(fixture.dispatcher.activities) == dispatch_count
    assert port.recover_graph(binding.run_id).pending_activity_results == ()
    node = next(item for item in recovered.node_instances if item.instance_id == fixture.activity.node_instance_id)
    assert node.output_refs["activity_result_lineage"]["candidate_checksum"] == envelope.candidate_checksum


def test_recovery_redispatches_marked_activity_without_result_after_restart() -> None:
    """A dispatched marker is not proof that physical execution completed."""

    fixture = _dispatched("run-dispatch-marker-crash-window")
    dispatch_count = len(fixture.dispatcher.activities)
    fixture.dispatcher.reconcile = lambda _activity: True
    recovery = fixture.port.recover_graph(fixture.activity.run_id)
    assert fixture.activity.activity_id in recovery.dispatched_activity_ids
    assert not recovery.activity_result_commits
    assert recovery.state is not None
    assert any(
        item.activity_id == fixture.activity.activity_id
        for item in recovery.state.active_activities
    )

    restarted = HarnessGraphControlPlaneRuntime(
        fixture.port,
        activity_dispatcher=fixture.dispatcher,
    )
    restarted.recover(
        fixture.activity.run_id,
        fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
    )

    assert len(fixture.dispatcher.activities) == dispatch_count + 1


def test_pending_result_cause_blocks_out_of_order_parallel_result() -> None:
    run_spec = _parallel_run_spec("run-result-out-of-order")
    port = FailResultProjectionPort()
    dispatcher = RecordingDispatcher()
    control_plane = _parallel_control_plane(port, dispatcher)
    running = control_plane.run(run_spec)
    assert running.state is not None
    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.graph is not None
    adapter = HarnessGraphResultRuntime(HarnessGraphControlPlaneRuntime(port))
    checksum = run_spec_checksum(run_spec)
    first, second = tuple(
        sorted(dispatcher.activities, key=lambda item: item.node_id)
    )
    first_binding = adapter.binding_for_activity(
        activity_id=first.activity_id,
        graph=recovery.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-first",
        run_spec_checksum=checksum,
    )
    second_binding = adapter.binding_for_activity(
        activity_id=second.activity_id,
        graph=recovery.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-second",
        run_spec_checksum=checksum,
    )
    port.fail_result_projection = True

    with pytest.raises(RuntimeError, match="result projection unavailable"):
        adapter.accept_materialized_result(
            _envelope(first_binding, inline_projection={"branch": first.node_id}),
            expected_binding=first_binding,
            activity_id=first.activity_id,
            graph=recovery.graph,
            run_spec_checksum=checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(HarnessValidationError) as out_of_order:
        adapter.accept_materialized_result(
            _envelope(second_binding, inline_projection={"branch": second.node_id}),
            expected_binding=second_binding,
            activity_id=second.activity_id,
            graph=recovery.graph,
            run_spec_checksum=checksum,
            occurred_at=NOW + timedelta(minutes=2),
        )
    assert out_of_order.value.code == "graph_recovery_required"

    interrupted = port.recover_graph(run_spec.run_id)
    assert len(interrupted.activity_result_commits) == 1
    assert interrupted.activity_result_commits[0].result.activity_id == first.activity_id
    HarnessGraphControlPlaneRuntime(port).recover(
        run_spec.run_id,
        recovery.graph,
        run_spec_checksum=checksum,
    )
    adapter.accept_materialized_result(
        _envelope(second_binding, inline_projection={"branch": second.node_id}),
        expected_binding=second_binding,
        activity_id=second.activity_id,
        graph=recovery.graph,
        run_spec_checksum=checksum,
        occurred_at=NOW + timedelta(minutes=3),
    )
    assert len(port.recover_graph(run_spec.run_id).activity_result_commits) == 2


def test_binding_and_projection_reject_cross_tenant_and_worker_control_fields() -> None:
    fixture = _dispatched("run-result-boundary")
    with pytest.raises(HarnessValidationError) as cross_tenant:
        fixture.adapter.binding_for_activity(
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            tenant_id=TENANT_ID,
            tenant_scope_ref=checksum_for("other-tenant-scope"),
            attempt_id="physical-attempt-1",
            run_spec_checksum=fixture.run_spec_checksum,
        )
    assert cross_tenant.value.code == "graph_result_lineage_scope_mismatch"

    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    wrong_scope_binding = replace(
        binding,
        tenant_scope_ref=checksum_for("other-tenant-scope"),
    )
    with pytest.raises(HarnessValidationError) as mismatched_binding:
        fixture.adapter.accept_materialized_result(
            _envelope(wrong_scope_binding),
            expected_binding=wrong_scope_binding,
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )
    assert mismatched_binding.value.code == "graph_result_lineage_scope_mismatch"

    unsafe = _envelope(binding, inline_projection={"route": "publish"})
    before = fixture.port.recover_graph(binding.run_id)
    with pytest.raises(HarnessValidationError) as forbidden:
        fixture.adapter.accept_materialized_result(
            unsafe,
            expected_binding=binding,
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )
    assert forbidden.value.code == "graph_result_lineage_projection_invalid"
    assert fixture.port.recover_graph(binding.run_id) == before


def test_oversized_worker_projection_is_rejected_before_durable_commit() -> None:
    fixture = _dispatched("run-result-oversized")
    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    oversized = _envelope(binding, inline_projection={"value": "x" * (33 * 1024)})
    before = fixture.port.recover_graph(binding.run_id)

    with pytest.raises(HarnessValidationError) as rejected:
        fixture.adapter.accept_materialized_result(
            oversized,
            expected_binding=binding,
            activity_id=fixture.activity.activity_id,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )

    assert rejected.value.code == "graph_result_lineage_projection_invalid"
    assert fixture.port.recover_graph(binding.run_id) == before


def test_artifact_result_state_size_is_independent_of_candidate_bytes() -> None:
    small_state = _accept_artifact_result("run-size-small", candidate_bytes=1_000_000)
    large_state = _accept_artifact_result("run-size-large", candidate_bytes=100_000_000)

    small_json = stable_json_dumps(small_state.to_dict())
    large_json = stable_json_dumps(large_state.to_dict())
    assert len(large_json) < len(small_json) + 256
    assert "raw-large-candidate" not in large_json
    large_node = next(
        item
        for item in large_state.node_instances
        if "activity_result_lineage" in item.output_refs
    )
    projection = large_node.output_refs["activity_result_lineage"]
    assert projection["inline_projection"] == {}
    assert projection["candidate_bytes"] == 100_000_000
    assert len(projection["artifact_refs"]) == 1


def test_parallel_lineage_stays_branch_scoped_and_replay_is_worker_free() -> None:
    run_spec = _parallel_run_spec("run-result-parallel")
    port = InMemoryHarnessEventPort()
    dispatcher = RecordingDispatcher()
    control_plane = _parallel_control_plane(port, dispatcher)

    running = control_plane.run(run_spec)

    assert running.state is not None
    assert {item.node_id for item in dispatcher.activities} == {"left", "right"}
    recovery = port.recover_graph(run_spec.run_id)
    assert recovery.graph is not None
    adapter = HarnessGraphResultRuntime(HarnessGraphControlPlaneRuntime(port))
    checksum = run_spec_checksum(run_spec)
    for activity in tuple(dispatcher.activities):
        _accept_external_materialized_result(
            adapter=adapter,
            port=port,
            activity=activity,
            graph=recovery.graph,
            run_spec_checksum_value=checksum,
            attempt_id=f"physical-{activity.node_id}",
            projection={"branch": activity.node_id},
        )

    aggregation = control_plane.recover_and_run(run_spec)

    assert aggregation.state is not None
    assert [item.node_id for item in dispatcher.activities].count("aggregate") == 1
    aggregate = dispatcher.activities[-1]
    _accept_external_materialized_result(
        adapter=adapter,
        port=port,
        activity=aggregate,
        graph=recovery.graph,
        run_spec_checksum_value=checksum,
        attempt_id="physical-aggregate",
        projection={"aggregate_ready": True},
    )
    completed = control_plane.recover_and_run(run_spec)

    assert completed.state is not None
    branch_nodes = {
        item.identity.node_id: item
        for item in completed.state.node_instances
        if item.identity.node_id in {"left", "right"}
    }
    assert {
        node.output_refs["activity_result_lineage"]["attempt_id"]
        for node in branch_nodes.values()
    } == {"physical-left", "physical-right"}
    assert {
        node.output_refs["activity_result_lineage"]["inline_projection"]["branch"]
        for node in branch_nodes.values()
    } == {"left", "right"}
    join_payload = stable_json_dumps(completed.state.join_states[0].to_dict())
    assert "inline_projection" not in join_payload
    assert "candidate_checksum" not in join_payload

    dispatch_count = len(dispatcher.activities)
    replayed = _parallel_control_plane(port, dispatcher).recover_and_run(run_spec)
    assert replayed.state is not None
    assert replayed.state.projection_checksum == (
        completed.state.projection_checksum
    )
    assert len(dispatcher.activities) == dispatch_count


class _Fixture:
    def __init__(self, *, port, dispatcher, activity, graph, run_spec_checksum, adapter) -> None:
        self.port = port
        self.dispatcher = dispatcher
        self.activity = activity
        self.graph = graph
        self.run_spec_checksum = run_spec_checksum
        self.adapter = adapter


def _dispatched(run_id: str, *, port=None) -> _Fixture:
    event_port = port or InMemoryHarnessEventPort()
    dispatcher = RecordingDispatcher()
    run_spec = _run_spec(run_id)
    side_effect_store = InMemoryHarnessSideEffectStore()
    terminal_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "graph-result-test@1",
                "artifact_publication",
                CountingHarnessSideEffectHandler(
                    side_effect_store,
                    disposition="accepted",
                ),
            ),
        )
    )
    control_plane = HarnessControlPlane(
        event_port=event_port,
        side_effect_store=side_effect_store,
        runtime_binding_authority=HarnessRuntimeBindingAuthority(
            workers=(
                HarnessWorkerBinding(
                    "analyze@1",
                    "function",
                    _ExternalWorker("analyze"),
                ),
            ),
            activities=(
                HarnessActivityContractBinding(
                    "newsroom.harness-worker-activity@v1",
                    _ParallelSafeActivity(),
                ),
            ),
            side_effect_registry=terminal_registry,
        ),
        graph_activity_dispatcher=dispatcher,
    )
    result = control_plane.run(run_spec)
    assert result.state is not None
    assert len(dispatcher.activities) == 1
    recovery = event_port.recover_graph(run_id)
    assert recovery.graph is not None
    checksum = run_spec_checksum(run_spec)
    assert recovery.run_spec_checksum == checksum
    adapter = HarnessGraphResultRuntime(HarnessGraphControlPlaneRuntime(event_port))
    return _Fixture(
        port=event_port,
        dispatcher=dispatcher,
        activity=dispatcher.activities[0],
        graph=recovery.graph,
        run_spec_checksum=checksum,
        adapter=adapter,
    )


def _run_spec(run_id: str) -> HarnessRunSpec:
    step = HarnessStepSpec(
        "analyze",
        "function",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    graph_spec = HarnessGraphSpec(
        graph_id=f"graph-{run_id}",
        root=StepRef("analyze"),
    )
    graph = HarnessGraphDefinition(
        graph_id=graph_spec.graph_id,
        graph_version="1",
        root=graph_spec,
        activities=(step,),
        leaf_activity_bindings=(
            HarnessGraphLeafBinding(
                "analyze",
                "function",
                HarnessContractReference(HarnessContractKind.WORKER, "analyze", "1"),
                HarnessContractReference(
                    HarnessContractKind.ACTIVITY,
                    "newsroom.harness-worker-activity",
                    "v1",
                ),
            ),
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="graph-result-test",
            version="1",
            handler="graph-result-test@1",
            kind="artifact_publication",
            requires_approval=False,
            retry_limit=1,
            not_required_evidence_ref=checksum_for("graph-result-test"),
        ),
    )
    return HarnessRunSpec(
        run_id=run_id,
        graph=graph,
        metadata={
            "tenant_scope_ref": TENANT_SCOPE_REF,
            "identity_scope_ref": TENANT_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        created_at=NOW,
    )


def _parallel_run_spec(run_id: str) -> HarnessRunSpec:
    steps = tuple(
        HarnessStepSpec(
            step_id,
            "function",
            output_key=f"{step_id}_output",
            metadata={"step_version": "1", "worker_version": "1"},
        )
        for step_id in ("left", "right", "aggregate")
    )
    return HarnessRunSpec(
        run_id=run_id,
        graph=HarnessGraphDefinition(
            graph_id=f"graph-{run_id}",
            graph_version="1",
            root=HarnessGraphSpec(
                graph_id=f"graph-{run_id}",
                root=Sequence(
                    (
                        ParallelAll(
                            "fork",
                            "join",
                            (
                                ParallelBranch(
                                    "left-branch",
                                    StepRef("left"),
                                    "parallel.left",
                                ),
                                ParallelBranch(
                                    "right-branch",
                                    StepRef("right"),
                                    "parallel.right",
                                ),
                            ),
                        ),
                        StepRef("aggregate"),
                    )
                ),
            ),
            activities=steps,
            leaf_activity_bindings=tuple(
                HarnessGraphLeafBinding(
                    step_id,
                    "function",
                    HarnessContractReference(HarnessContractKind.WORKER, step_id, "1"),
                    HarnessContractReference(
                        HarnessContractKind.ACTIVITY,
                        "newsroom.harness-worker-activity",
                        "v1",
                    ),
                )
                for step_id in ("left", "right", "aggregate")
            ),
            task_plan_stage_bindings=(),
            committed_output_bindings=(),
            repair_bindings=(),
            terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
                policy_id="graph-result-test",
                version="1",
                handler="graph-result-test@1",
                kind="artifact_publication",
                requires_approval=False,
                retry_limit=1,
                not_required_evidence_ref=checksum_for("graph-result-test"),
            ),
        ),
        metadata={
            "tenant_scope_ref": TENANT_SCOPE_REF,
            "identity_scope_ref": TENANT_SCOPE_REF,
            "subject_scope_ref": SUBJECT_SCOPE_REF,
        },
        created_at=NOW,
    )


def _parallel_control_plane(port, dispatcher) -> HarnessControlPlane:
    side_effect_store = InMemoryHarnessSideEffectStore()
    terminal_registry = HarnessSideEffectRegistry(
        (
            HarnessSideEffectHandlerBinding(
                "graph-result-test@1",
                "artifact_publication",
                CountingHarnessSideEffectHandler(
                    side_effect_store,
                    disposition="accepted",
                ),
            ),
        )
    )
    return HarnessControlPlane(
        event_port=port,
        side_effect_store=side_effect_store,
        runtime_binding_authority=HarnessRuntimeBindingAuthority(
            workers=tuple(
                HarnessWorkerBinding(
                    f"{step_id}@1",
                    "function",
                    _ExternalWorker(step_id),
                )
                for step_id in ("left", "right", "aggregate")
            ),
            activities=(
                HarnessActivityContractBinding(
                    "newsroom.harness-worker-activity@v1",
                    _ParallelSafeActivity(),
                ),
            ),
            side_effect_registry=terminal_registry,
        ),
        graph_preflight=HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(
                max_node_activations=20,
                max_active_nodes=4,
                max_parallelism=2,
            )
        ),
        graph_activity_dispatcher=dispatcher,
    )


def _accept_external_materialized_result(
    *,
    adapter,
    port,
    activity,
    graph,
    run_spec_checksum_value,
    attempt_id,
    projection,
) -> None:
    binding = adapter.binding_for_activity(
        activity_id=activity.activity_id,
        graph=graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id=attempt_id,
        run_spec_checksum=run_spec_checksum_value,
    )
    worker_result = HarnessWorkerResult(
        "succeeded",
        output={"step_id": activity.node_id},
    )
    port.activity_results[activity.activity_id] = worker_result
    adapter.accept_materialized_result(
        _envelope(binding, inline_projection=projection),
        expected_binding=binding,
        activity_id=activity.activity_id,
        graph=graph,
        run_spec_checksum=run_spec_checksum_value,
        occurred_at=NOW + timedelta(minutes=activity.causal_decision_sequence),
    )


def _envelope(binding, *, inline_projection=None) -> NodeResultEnvelope:
    projection = {"count": 1} if inline_projection is None else inline_projection
    summary = BoundedSummary.from_text("bounded result")
    candidate_bytes = 17
    return NodeResultEnvelope(
        binding=binding,
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="graph-result@1",
        output_schema_digest=SCHEMA_DIGEST,
        candidate_checksum=checksum_for("candidate-1"),
        summary=summary,
        inline_projection=projection,
        materialized_refs=(),
        cache_refs=(),
        provenance=ResultProvenance(
            producer_ref="worker@1",
            producer_revision="worker-revision@abc123",
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


def _accept_artifact_result(run_id: str, *, candidate_bytes: int):
    fixture = _dispatched(run_id)
    binding = fixture.adapter.binding_for_activity(
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        attempt_id="physical-attempt-1",
        run_spec_checksum=fixture.run_spec_checksum,
    )
    checksum = checksum_for(f"candidate-size-{candidate_bytes}")
    summary = BoundedSummary.from_text("large result stored by reference")
    artifact = ArtifactRecord(
        ref=f"artifact://{TENANT_ID}/{run_id}/physical-attempt-1",
        artifact_id="result-artifact",
        artifact_type="node_result",
        content_checksum=checksum,
        byte_size=candidate_bytes,
        media_type="application/json",
        artifact_class=ArtifactClass.INTERMEDIATE,
        tenant_id=TENANT_ID,
        run_id=run_id,
        graph_id=binding.graph_id,
        node_id=binding.node_id,
        attempt_id=binding.attempt_id,
        producer_revision="worker-revision@abc123",
        sensitivity=ResultSensitivity.INTERNAL,
        reusable=False,
        dependency_digest=None,
        retention_class=RetentionClass.RUN,
        expires_at=NOW + timedelta(days=30),
        required_for_replay=True,
        required_for_publication=False,
        created_at=NOW,
    )
    envelope = NodeResultEnvelope(
        binding=binding,
        status=NodeResultStatus.SUCCEEDED,
        output_schema_ref="graph-result@1",
        output_schema_digest=SCHEMA_DIGEST,
        candidate_checksum=checksum,
        summary=summary,
        inline_projection={},
        materialized_refs=(artifact,),
        cache_refs=(),
        provenance=ResultProvenance(
            producer_ref="worker@1",
            producer_revision="worker-revision@abc123",
        ),
        persistence_decision=PersistenceDecision(
            mode=PersistenceMode.ARTIFACT,
            reason=PersistenceReason.REQUIRED_FOR_REPLAY,
            artifact_class=ArtifactClass.INTERMEDIATE,
            retention_class=RetentionClass.RUN,
            estimated_bytes=candidate_bytes,
            reserved_bytes=candidate_bytes,
            context_policy=ContextPolicy.SUMMARY_ONLY,
            required=True,
            policy_version="graph-artifact-policy@1",
        ),
        metrics=ResultMetrics(
            candidate_bytes=candidate_bytes,
            candidate_tokens=(candidate_bytes + 3) // 4,
            summary_bytes=summary.byte_size,
            inline_bytes=0,
        ),
        created_at=NOW,
    )
    return fixture.adapter.accept_materialized_result(
        envelope,
        expected_binding=binding,
        activity_id=fixture.activity.activity_id,
        graph=fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=1),
    )
