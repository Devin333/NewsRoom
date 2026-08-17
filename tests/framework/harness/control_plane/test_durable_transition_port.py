from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import (
    ProducerIdentity,
    StoredEvent,
    checksum_for,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventStoreCorruptionError,
)
from framework.events.runtime.publisher import EventRuntime
from framework.events.runtime.models import StreamReadRequest
from framework.events.schema import default_event_schema_catalog
from framework.harness.control_plane.durable_events import (
    DurableHarnessTransitionPort,
    HarnessEventCanonicalAdapter,
)
from framework.harness.graph.decision import HarnessGraphDecisionType
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphObservationType,
)
from framework.harness.control_plane.graph_operations import (
    HarnessGraphRunOperation,
    HarnessGraphRunOperationType,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphCommitKind,
)
from framework.harness.control_plane.graph_state import HarnessJoinStatus
from framework.harness.control_plane.harness import HarnessControlPlane
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.graph.dsl import (
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    StepRef,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)


class _RecordingGraphDispatcher:
    def __init__(self) -> None:
        self.activities: list[HarnessGraphActivity] = []
        self.cancellations: list[object] = []

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        self.activities.append(activity)

    def request_cancellation(self, request: object) -> None:
        self.cancellations.append(request)


class _TamperingReader:
    """Return immutable, checksum-consistent fixtures that differ from storage."""

    def __init__(self, reader, transform) -> None:
        self._reader = reader
        self._transform = transform

    def get_event(self, event_id: str, *, tenant_id: str | None = None):
        event = self._reader.get_event(event_id, tenant_id=tenant_id)
        return None if event is None else self._transform(event)

    def read_stream(self, request):
        page = self._reader.read_stream(request)
        return replace(
            page,
            events=tuple(self._transform(event) for event in page.events),
        )

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ):
        return self._reader.get_stream_high_watermark(
            stream_id,
            tenant_id=tenant_id,
        )


class _CountingReader(_TamperingReader):
    def __init__(self, reader) -> None:
        super().__init__(reader, lambda event: event)
        self.requests: list[StreamReadRequest] = []

    def read_stream(self, request):
        self.requests.append(request)
        return super().read_stream(request)


def _rewrite_stored_event(event: StoredEvent, **candidate_fields) -> StoredEvent:
    candidate = replace(event.candidate, **candidate_fields)
    return StoredEvent(
        candidate=candidate,
        observed_at=event.observed_at,
        stream_sequence=event.stream_sequence,
    )


def _graph_control_plane(
    port: DurableHarnessTransitionPort,
    *,
    dispatcher: _RecordingGraphDispatcher | None = None,
) -> HarnessControlPlane:
    return HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda _task: None},
        graph_activity_dispatcher=dispatcher,
    )


def _activate_graph(
    control_plane: HarnessControlPlane,
    run_spec: HarnessRunSpec,
):
    initial = control_plane.initialize_graph(run_spec)
    decision = control_plane.next_graph_decision(run_spec, initial)
    assert decision is not None
    assert decision.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    return initial, control_plane.apply_graph_decision(
        run_spec,
        initial,
        decision,
        occurred_at=NOW + timedelta(microseconds=1),
    )


def _dispatch_graph_activity(
    control_plane: HarnessControlPlane,
    port: DurableHarnessTransitionPort,
    run_spec: HarnessRunSpec,
    dispatcher: _RecordingGraphDispatcher,
):
    _, ready = _activate_graph(control_plane, run_spec)
    recovery = port.recover_graph(run_spec.run_id)
    enter_plan = control_plane.next_graph_decision(
        run_spec,
        ready,
        graph_context=control_plane._graph_evaluation_context(
            run_spec,
            ready,
            recovery,
        ),
        step_inputs=control_plane._graph_step_inputs(
            run_spec,
            ready,
            recovery,
        ),
    )
    assert enter_plan is not None
    planning = control_plane.apply_graph_decision(
        run_spec,
        ready,
        enter_plan,
        occurred_at=NOW + timedelta(microseconds=2),
    )
    recovery = port.recover_graph(run_spec.run_id)
    dispatch = control_plane.next_graph_decision(
        run_spec,
        planning,
        graph_context=control_plane._graph_evaluation_context(
            run_spec,
            planning,
            recovery,
        ),
        step_inputs=control_plane._graph_step_inputs(
            run_spec,
            planning,
            recovery,
        ),
    )
    assert dispatch is not None
    assert dispatch.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY
    running = control_plane.apply_graph_decision(
        run_spec,
        planning,
        dispatch,
        occurred_at=NOW + timedelta(microseconds=3),
        activity_input_ref=_sha("graph-worker-input"),
    )
    assert dispatcher.activities
    return running, dispatcher.activities[-1]


def _sha(value: str) -> str:
    return checksum_for({"value": value})


def _tampered_projection_payload(
    event: StoredEvent,
    projection,
) -> dict[str, object]:
    assert event.payload is not None
    raw = dict(thaw_canonical_json(event.payload["commit"]))
    if "state_summary" not in raw:
        return {"commit": projection.to_dict()}
    raw["projection_checksum"] = projection.state.projection_checksum
    raw["projection_commit_checksum"] = projection.commit_checksum
    raw["record_checksum"] = checksum_for(
        {key: value for key, value in raw.items() if key != "record_checksum"}
    )
    return {"commit": raw}


def _run_spec() -> HarnessRunSpec:
    return HarnessRunSpec(
        run_id="run-durable-transition",
        workflow=HarnessWorkflowSpec(
            workflow_id="durable-transition",
            steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
        created_at=NOW,
    )


def _runtime(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    return store, runtime


def test_durable_graph_round_trips_run_operation_before_cancellation_dispatch(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    port = DurableHarnessTransitionPort(runtime, store)
    dispatcher = _RecordingGraphDispatcher()
    control_plane = _graph_control_plane(port, dispatcher=dispatcher)
    run_spec = _run_spec()
    running, _ = _dispatch_graph_activity(
        control_plane,
        port,
        run_spec,
        dispatcher,
    )
    operation = HarnessGraphRunOperation(
        HarnessGraphRunOperationType.CANCEL,
        "durable-cancel-1",
        run_spec.run_id,
        _sha("durable-operation-actor"),
        "operator_cancelled",
        0,
    )

    accepted = control_plane.accept_graph_run_operation(
        run_spec,
        operation,
        occurred_at=NOW + timedelta(microseconds=4),
    )
    recovered_port = DurableHarnessTransitionPort(runtime, store)
    recovered = recovered_port.recover_graph(run_spec.run_id)

    assert recovered.state is not None
    assert recovered.state.last_event_sequence > running.last_event_sequence
    assert recovered.state.metadata["pending_run_operation"]["operation_ref"] == (
        accepted.operation_ref
    )
    assert recovered.observation_commits[-1].observation.evidence_ref == (
        accepted.operation_ref
    )
    assert dispatcher.cancellations == []

    pending = control_plane.recover_and_run(run_spec)

    assert pending.graph_state is not None
    assert pending.graph_state.node_instances[0].status.value == "cancel_requested"
    assert len(dispatcher.cancellations) == 1
    verified = control_plane.verify_graph_history(run_spec)
    assert verified.projection_checksum == pending.graph_state.projection_checksum


def test_durable_graph_recovers_open_parallel_join_scope(tmp_path) -> None:
    store, runtime = _runtime(tmp_path)
    port = DurableHarnessTransitionPort(runtime, store)
    run_spec = HarnessRunSpec(
        run_id="run-durable-parallel-fork",
        workflow=HarnessWorkflowSpec(
            workflow_id="durable-parallel-fork",
            steps=(
                HarnessStepSpec("left", "script"),
                HarnessStepSpec("right", "script"),
            ),
            entry_step_id="left",
            graph=HarnessGraphSpec(
                "durable-parallel-fork",
                ParallelAll(
                    "fork",
                    "join",
                    (
                        ParallelBranch("left-branch", StepRef("left"), "parallel.left"),
                        ParallelBranch(
                            "right-branch",
                            StepRef("right"),
                            "parallel.right",
                        ),
                    ),
                ),
            ),
        ),
        created_at=NOW,
    )
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"left": lambda _task: None, "right": lambda _task: None},
    )
    state = control_plane.initialize_graph(run_spec)
    activate = control_plane.next_graph_decision(run_spec, state)
    assert activate is not None
    state = control_plane.apply_graph_decision(
        run_spec,
        state,
        activate,
        occurred_at=NOW + timedelta(microseconds=1),
    )
    open_fork = control_plane.next_graph_decision(run_spec, state)
    assert open_fork is not None
    assert open_fork.decision_type is HarnessGraphDecisionType.OPEN_FORK
    opened = control_plane.apply_graph_decision(
        run_spec,
        state,
        open_fork,
        occurred_at=NOW + timedelta(microseconds=3),
    )

    recovered = HarnessControlPlane(
        event_port=DurableHarnessTransitionPort(runtime, store),
        worker_registry={"left": lambda _task: None, "right": lambda _task: None},
    ).recover_graph(run_spec)

    assert recovered == opened
    assert len(recovered.join_states) == 1
    join = recovered.join_states[0]
    assert join.status is HarnessJoinStatus.OPEN
    assert join.required_branch_ids == ("left-branch", "right-branch")
    assert join.completed_branch_instances == {}


def test_graph_recovery_tracks_canonical_high_watermark_across_non_graph_gap(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    port = DurableHarnessTransitionPort(runtime, store)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda _task: None},
    )

    initial = control_plane.initialize_graph(run_spec)
    activate = control_plane.next_graph_decision(run_spec, initial)
    assert activate is not None
    assert activate.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    ready = control_plane.apply_graph_decision(
        run_spec,
        initial,
        activate,
        occurred_at=NOW + timedelta(microseconds=1),
    )
    port.record(
        HarnessEvent(
            event_type=HarnessEventType.RUN_CREATED,
            run_id=run_spec.run_id,
            occurred_at=NOW + timedelta(microseconds=2),
        )
    )
    recovery = port.recover_graph(run_spec.run_id)
    enter_plan = control_plane.next_graph_decision(
        run_spec,
        ready,
        graph_context=control_plane._graph_evaluation_context(
            run_spec,
            ready,
            recovery,
        ),
        step_inputs=control_plane._graph_step_inputs(
            run_spec,
            ready,
            recovery,
        ),
    )
    assert enter_plan is not None
    assert enter_plan.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE
    projected = control_plane.apply_graph_decision(
        run_spec,
        ready,
        enter_plan,
        occurred_at=NOW + timedelta(microseconds=3),
    )

    recovered = DurableHarnessTransitionPort(runtime, store).recover_graph(
        run_spec.run_id
    )
    page = store.read_stream(
        StreamReadRequest(stream_id=f"run:{run_spec.run_id}", limit=20)
    )

    assert [event.stream_sequence for event in page.events] == [1, 2, 3, 4, 5, 6]
    assert [item.sequence for item in recovered.decision_commits] == [2, 5]
    assert [item.sequence for item in recovered.projection_commits] == [1, 3, 6]
    assert recovered.expected_last_sequence == 6
    assert recovered.state == projected
    assert recovered.state.last_event_sequence == 6


def test_graph_recovery_reads_only_new_suffix_after_cached_projection(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    writer = DurableHarnessTransitionPort(runtime, store)
    control_plane = HarnessControlPlane(
        event_port=writer,
        worker_registry={"collect": lambda _task: None},
    )
    initial = control_plane.initialize_graph(run_spec)
    decision = control_plane.next_graph_decision(run_spec, initial)
    assert decision is not None
    ready = control_plane.apply_graph_decision(
        run_spec,
        initial,
        decision,
        occurred_at=NOW + timedelta(microseconds=1),
    )

    reader = _CountingReader(store)
    cached_port = DurableHarnessTransitionPort(runtime, reader)
    cached = cached_port.recover_graph(run_spec.run_id)
    assert cached.expected_last_sequence == ready.last_event_sequence
    assert reader.requests
    reader.requests.clear()

    writer.record(
        HarnessEvent(
            event_type=HarnessEventType.RUN_CREATED,
            run_id=run_spec.run_id,
            occurred_at=NOW + timedelta(microseconds=2),
        )
    )
    advanced = cached_port.recover_graph(run_spec.run_id)
    assert len(reader.requests) == 1
    assert reader.requests[0].cursor is not None
    assert reader.requests[0].cursor.after_sequence == cached.expected_last_sequence
    assert advanced.expected_last_sequence == cached.expected_last_sequence + 1

    reader.requests.clear()
    cached_port.recover_graph(run_spec.run_id)
    assert reader.requests == []


@pytest.mark.parametrize("cause_kind", ("decision", "activity_result", "observation"))
def test_graph_recovery_fails_closed_when_non_graph_tail_follows_pending_cause(
    tmp_path,
    cause_kind: str,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()

    if cause_kind == "decision":
        port = DurableHarnessTransitionPort(runtime, store)
        control_plane = _graph_control_plane(port)
        initial = control_plane.initialize_graph(run_spec)
        decision = control_plane.next_graph_decision(run_spec, initial)
        assert decision is not None
        port.commit_graph_decision(
            decision,
            occurred_at=NOW + timedelta(microseconds=1),
            expected_last_sequence=1,
        )
    elif cause_kind == "activity_result":
        dispatcher = _RecordingGraphDispatcher()
        port = DurableHarnessTransitionPort(runtime, store)
        control_plane = _graph_control_plane(port, dispatcher=dispatcher)
        running, activity = _dispatch_graph_activity(
            control_plane,
            port,
            run_spec,
            dispatcher,
        )
        result = HarnessGraphActivityResult.for_activity(
            activity,
            evidence_ref=_sha("pending-activity-result"),
            payload_ref=_sha("pending-activity-payload"),
            status="succeeded",
        )
        port.commit_graph_activity_result(
            result,
            occurred_at=NOW + timedelta(microseconds=4),
            expected_last_sequence=running.last_event_sequence,
        )
    else:
        dispatcher = _RecordingGraphDispatcher()
        port = DurableHarnessTransitionPort(runtime, store)
        control_plane = _graph_control_plane(port, dispatcher=dispatcher)
        running, _ = _dispatch_graph_activity(
            control_plane,
            port,
            run_spec,
            dispatcher,
        )
        graph = control_plane._prepared_graphs[run_spec.run_id]
        node = running.node_instances[0]
        definition = next(
            item for item in graph.nodes if item.node_id == node.identity.node_id
        )
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.WORKER_STATUS,
            definition.node_id,
            node.instance_id,
            node.attempt,
            running.last_event_sequence + 1,
            definition.worker_ref,
            _sha("pending-observation"),
            payload={"status": "succeeded"},
        )
        port.commit_graph_observation(
            observation,
            occurred_at=NOW + timedelta(microseconds=4),
            expected_last_sequence=running.last_event_sequence,
        )

    port.record(
        HarnessEvent(
            event_type=HarnessEventType.RUN_CREATED,
            run_id=run_spec.run_id,
            occurred_at=NOW + timedelta(microseconds=5),
        )
    )

    with pytest.raises(EventStoreCorruptionError, match="unprojected causal"):
        DurableHarnessTransitionPort(runtime, store).recover_graph(run_spec.run_id)


def test_graph_recovery_rejects_known_graph_event_with_wrong_data_schema(tmp_path) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    writer = DurableHarnessTransitionPort(runtime, store)
    _graph_control_plane(writer).initialize_graph(run_spec)

    reader = _TamperingReader(
        store,
        lambda event: _rewrite_stored_event(
            event,
            data_schema="newsroom.harness-graph-control-commit/v999",
        )
        if event.event_type == "harness_graph_initialized"
        else event,
    )
    recovered_port = DurableHarnessTransitionPort(runtime, reader)

    with pytest.raises(EventStoreCorruptionError, match="unsupported schema"):
        recovered_port.recover_graph(run_spec.run_id)


def test_graph_recovery_rejects_graph_event_from_another_producer(tmp_path) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    writer = DurableHarnessTransitionPort(runtime, store)
    _graph_control_plane(writer).initialize_graph(run_spec)

    reader = _TamperingReader(
        store,
        lambda event: _rewrite_stored_event(
            event,
            producer=ProducerIdentity(component="untrusted.graph.writer", version="9"),
        )
        if event.event_type == "harness_graph_initialized"
        else event,
    )
    recovered_port = DurableHarnessTransitionPort(runtime, reader)

    with pytest.raises(EventStoreCorruptionError, match="envelope"):
        recovered_port.recover_graph(run_spec.run_id)


def test_tenant_adapter_identity_scope_rejects_worker_activity_before_acceptance(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    port = DurableHarnessTransitionPort(
        runtime,
        store,
        # The scope guard runs before ActivityRecorder touches its store. A
        # sentinel keeps this boundary test independent of optional crypto
        # dependencies while the canonical event history remains SQLite-backed.
        activity_store=object(),
        adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-a"),
    )
    activity = port.create_activity(
        run_id="run-identity-bound-worker",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs={"query": "identity"},
    )
    cross_tenant_activity = replace(
        activity,
        identity_scope_ref=checksum_for("tenant-b"),
    )

    with pytest.raises(HarnessValidationError, match="identity scope"):
        port.accept_activity(
            cross_tenant_activity,
            {"query": "identity"},
            accepted_at=NOW,
            started_at=NOW,
        )


@pytest.mark.parametrize("tamper", ("cross_node", "cross_attempt", "wrong_contract"))
def test_graph_observation_projection_replay_fails_closed_when_paired_state_is_tampered(
    tmp_path,
    tamper: str,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    dispatcher = _RecordingGraphDispatcher()
    port = DurableHarnessTransitionPort(runtime, store)
    control_plane = _graph_control_plane(port, dispatcher=dispatcher)
    running, _ = _dispatch_graph_activity(
        control_plane,
        port,
        run_spec,
        dispatcher,
    )
    graph = control_plane._prepared_graphs[run_spec.run_id]
    node = running.node_instances[0]
    definition = next(
        item for item in graph.nodes if item.node_id == node.identity.node_id
    )
    observation = HarnessAcceptedGraphObservation(
        HarnessGraphObservationType.WORKER_STATUS,
        definition.node_id,
        node.instance_id,
        node.attempt,
        running.last_event_sequence + 1,
        definition.worker_ref,
        _sha(f"observation-{tamper}"),
        payload={"status": "succeeded"},
    )
    projected = control_plane.accept_graph_observation(
        run_spec,
        observation,
        occurred_at=NOW + timedelta(microseconds=4),
    )
    recovery = port.recover_graph(run_spec.run_id)
    observation_projection = next(
        item
        for item in recovery.projection_commits
        if item.commit_kind is HarnessGraphCommitKind.OBSERVATION_PROJECTION
    )
    projected_node = next(
        item
        for item in projected.node_instances
        if item.instance_id == node.instance_id
    )
    evidence = projected_node.evidence_refs[-1]
    if tamper == "cross_node":
        metadata = dict(projected_node.metadata)
        accepted = [dict(item) for item in metadata["accepted_observations"]]
        logical_identity = list(accepted[-1]["logical_identity"])
        logical_identity[0] = "hni_cross_node_tamper"
        accepted[-1]["logical_identity"] = tuple(logical_identity)
        metadata["accepted_observations"] = accepted
        tampered_node = replace(projected_node, metadata=metadata)
    elif tamper == "cross_attempt":
        metadata = dict(projected_node.metadata)
        accepted = [dict(item) for item in metadata["accepted_observations"]]
        logical_identity = list(accepted[-1]["logical_identity"])
        logical_identity[1] = evidence.attempt + 1
        accepted[-1]["logical_identity"] = tuple(logical_identity)
        metadata["accepted_observations"] = accepted
        tampered_node = replace(projected_node, metadata=metadata)
    else:
        assert evidence.contract_ref is not None
        tampered_evidence = replace(
            evidence,
            contract_ref=replace(
                evidence.contract_ref,
                contract_id="worker.tampered",
            ),
        )
        tampered_node = replace(
            projected_node,
            evidence_refs=(*projected_node.evidence_refs[:-1], tampered_evidence),
        )
    tampered_state = replace(
        observation_projection.state,
        node_instances=tuple(
            tampered_node if item.instance_id == tampered_node.instance_id else item
            for item in observation_projection.state.node_instances
        ),
        projection_checksum=None,
    )
    tampered_projection = replace(observation_projection, state=tampered_state)
    reader = _TamperingReader(
        store,
        lambda event: _rewrite_stored_event(
            event,
            payload=_tampered_projection_payload(event, tampered_projection),
        )
        if (
            event.event_type == "harness_graph_projection_committed"
            and event.stream_sequence == observation_projection.sequence
        )
        else event,
    )

    with pytest.raises(
        EventStoreCorruptionError,
        match="pure replay",
    ):
        DurableHarnessTransitionPort(runtime, reader).recover_graph(run_spec.run_id)
