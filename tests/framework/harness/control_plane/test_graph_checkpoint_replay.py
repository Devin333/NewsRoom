from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events.canonical import checksum_for
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.events.schema.catalog import (
    HARNESS_GRAPH_TRANSITION_EVENT_SCHEMAS,
    default_event_schema_catalog,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_checkpoint import (
    HarnessGraphCheckpoint,
    HarnessGraphCheckpointReader,
    HarnessGraphHistoryReducer,
    HarnessGraphStateReader,
    HarnessLegacyEventReader,
    HarnessPinnedDecisionKernel,
    InMemoryHarnessGraphCheckpointStore,
    graph_history_evidence_ref,
)
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    HarnessRunResult,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.state import HarnessRunSpec
from framework.harness.runtime.checkpoint import HarnessCheckpoint
from framework.harness.graph.dsl import HarnessGraphSpec, Sequence, StepRef
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    LEGACY_CHECKPOINT_SCHEMA,
    LEGACY_EVENT_SCHEMA,
    LEGACY_STATE_SCHEMA,
    HarnessGraphContractKind,
)
from framework.harness.workers.result import HarnessWorkerResult


_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def test_graph_history_rebuild_and_checkpoint_resume_are_pure_and_exact() -> None:
    control_plane, event_port, run_spec, _ = _completed_run("run-graph-checkpoint")
    recovery = event_port.recover_graph(run_spec.run_id)
    reducer = HarnessGraphHistoryReducer()

    rebuilt = reducer.rebuild(recovery)
    verified = control_plane.verify_graph_history(run_spec)
    checkpoint_state = recovery.projection_commits[
        len(recovery.projection_commits) // 2
    ].state
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-mid-run",
        checkpoint_state,
        created_at=_NOW,
        history_evidence_ref=graph_history_evidence_ref(
            recovery,
            through_sequence=checkpoint_state.last_event_sequence,
            projection_checksum=checkpoint_state.projection_checksum,
        ),
    )
    resumed = control_plane.verify_graph_history(
        run_spec,
        checkpoint=checkpoint,
    )

    assert rebuilt.state == control_plane.recover_graph(run_spec)
    assert verified.state == rebuilt.state
    assert resumed.state == rebuilt.state
    assert rebuilt.projection_checksum == recovery.state.projection_checksum
    assert rebuilt.verified_decision_checksums == ()
    assert verified.verified_decision_checksums
    assert resumed.verified_decision_checksums == verified.verified_decision_checksums
    assert resumed.applied_projection_sequences[0] > checkpoint.last_event_sequence
    assert rebuilt.pending_cause_checksums == ()


def test_graph_checkpoint_roundtrip_store_and_tamper_detection() -> None:
    _, event_port, run_spec, _ = _completed_run("run-checkpoint-roundtrip")
    state = event_port.recover_graph(run_spec.run_id).state
    assert state is not None
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-roundtrip",
        state,
        created_at=_NOW,
    )
    store = InMemoryHarnessGraphCheckpointStore()

    assert HarnessGraphCheckpoint.from_dict(checkpoint.to_dict()) == checkpoint
    assert store.save(checkpoint) == checkpoint
    assert store.load(checkpoint.checkpoint_id) == checkpoint

    tampered = checkpoint.to_dict()
    tampered["projection_checksum"] = checksum_for("tampered")
    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphCheckpoint.from_dict(tampered)
    assert captured.value.code == "graph_checkpoint_checksum_mismatch"


def test_verify_history_rejects_a_conflicting_pinned_decision_kernel() -> None:
    _, event_port, run_spec, _ = _completed_run("run-verify-decision-kernel")
    recovery = event_port.recover_graph(run_spec.run_id)

    kernel = HarnessPinnedDecisionKernel(
        recovery.graph,
        lambda _state, commit: replace(
            commit.decision,
            reason_code="different_replay_decision",
        ),
    )

    with pytest.raises(EventReplayMismatchError, match="pinned decision kernel"):
        HarnessGraphHistoryReducer().rebuild(
            recovery,
            verify_history=True,
            decision_kernel=kernel,
        )


def test_checkpoint_reader_quarantines_unknown_or_incompatible_graphs() -> None:
    _, event_port, run_spec, _ = _completed_run("run-checkpoint-quarantine")
    state = event_port.recover_graph(run_spec.run_id).state
    assert state is not None
    checkpoint = HarnessGraphCheckpoint.from_state(
        "checkpoint-quarantine",
        state,
        created_at=_NOW,
    )
    reader = HarnessGraphCheckpointReader()

    unknown = reader.read_or_quarantine(
        {"schema_version": "newsroom.harness-graph-checkpoint/v999"}
    )
    incompatible = reader.read_or_quarantine(
        checkpoint.to_dict(),
        expected_graph_ref=replace(
            checkpoint.graph_ref,
            checksum=checksum_for("another-graph"),
        ),
    )

    assert unknown.quarantined
    assert unknown.quarantine_reason == "unsupported_graph_checkpoint_schema"
    assert incompatible.quarantined
    assert incompatible.quarantine_reason == "graph_checkpoint_graph_mismatch"


def test_legacy_checkpoint_upcast_requires_rebuilt_history_evidence() -> None:
    _, event_port, run_spec, result = _completed_run("run-checkpoint-upcast")
    graph_state = event_port.recover_graph(run_spec.run_id).state
    assert graph_state is not None
    legacy = HarnessCheckpoint(
        checkpoint_id="legacy-checkpoint",
        run_id=run_spec.run_id,
        state=result.state,
        created_at=_NOW,
    )
    value = {"schema_version": LEGACY_CHECKPOINT_SCHEMA, **legacy.to_dict()}

    upcast = HarnessGraphCheckpointReader().upcast_legacy(
        value,
        rebuilt_state=graph_state,
        last_event_sequence=graph_state.last_event_sequence,
        history_evidence_ref=checksum_for("verified-v1-history"),
    )

    assert not upcast.quarantined
    assert upcast.checkpoint is not None
    assert upcast.checkpoint.state == graph_state
    assert upcast.applied_upcasters == (
        "newsroom.harness-checkpoint-legacy/v1->newsroom.harness-graph-checkpoint/v1",
    )


def test_replay_high_watermark_verifies_pending_decision_without_appending() -> None:
    control_plane, event_port, run_spec, _ = _completed_run("run-replay-high-watermark")
    recovery = event_port.recover_graph(run_spec.run_id)
    decision = recovery.decision_commits[len(recovery.decision_commits) // 2]
    event_count = len(event_port.events)

    report = control_plane.verify_graph_history(
        run_spec,
        through_sequence=decision.sequence,
    )

    assert report.through_sequence == decision.sequence
    assert report.pending_cause_checksums == (decision.decision.decision_checksum,)
    assert report.verified_decision_checksums[-1] == (
        decision.decision.decision_checksum
    )
    assert len(event_port.events) == event_count


def test_verify_history_without_a_pinned_kernel_is_quarantined() -> None:
    _, event_port, run_spec, _ = _completed_run("run-replay-kernel-missing")

    result = HarnessGraphHistoryReducer().rebuild_or_quarantine(
        event_port.recover_graph(run_spec.run_id),
        verify_history=True,
    )

    assert result.quarantined
    assert result.quarantine_reason == "graph_history_evidence_missing"
    assert result.report is None


@pytest.mark.parametrize(
    ("failure", "reason"),
    (
        (
            EventStoreCorruptionError("corrupt graph source"),
            "corrupt_graph_history",
        ),
        (
            EventIncompleteHistoryError("missing graph evidence"),
            "graph_history_evidence_missing",
        ),
        (
            HarnessValidationError(
                "unknown graph event version",
                code="unsupported_graph_event_version",
            ),
            "unsupported_graph_history_version",
        ),
    ),
)
def test_control_plane_quarantines_corrupt_unknown_or_incomplete_history(
    failure: Exception,
    reason: str,
) -> None:
    control_plane, event_port, run_spec, _ = _completed_run(
        f"run-source-quarantine-{reason}"
    )

    def fail_recovery(_run_id: str):
        raise failure

    event_port.recover_graph = fail_recovery  # type: ignore[method-assign]

    result = control_plane.verify_graph_history_or_quarantine(run_spec)

    assert result.quarantined
    assert result.quarantine_reason == reason
    assert result.report is None


def test_legacy_state_event_and_checkpoint_upcasters_are_evidence_bound() -> None:
    _, event_port, run_spec, result = _completed_run("run-v1-evidence-upcast")
    graph_state = event_port.recover_graph(run_spec.run_id).state
    assert graph_state is not None
    history_ref = checksum_for("verified-v1-history")
    legacy_state = {
        "schema_version": LEGACY_STATE_SCHEMA,
        **result.state.to_dict(),
    }
    state_result = HarnessGraphStateReader().read_or_quarantine(
        legacy_state,
        rebuilt_state=graph_state,
        history_evidence_ref=history_ref,
        expected_graph_ref=graph_state.graph_ref,
    )
    legacy_event = {
        "schema_version": LEGACY_EVENT_SCHEMA,
        **result.events[0].to_dict(),
    }
    event_result = HarnessLegacyEventReader().read_or_quarantine(
        legacy_event,
        stream_sequence=1,
        history_evidence_ref=history_ref,
        expected_run_id=run_spec.run_id,
    )

    assert not state_result.quarantined
    assert state_result.state == graph_state
    assert state_result.source_checksum is not None
    assert not event_result.quarantined
    assert event_result.evidence is not None
    assert event_result.evidence.run_id == run_spec.run_id
    assert event_result.evidence.history_evidence_ref == history_ref

    missing_state_evidence = HarnessGraphStateReader().read_or_quarantine(
        legacy_state,
        rebuilt_state=graph_state,
    )
    missing_event_evidence = HarnessLegacyEventReader().read_or_quarantine(
        legacy_event,
        stream_sequence=1,
        history_evidence_ref=None,
    )
    corrupt_event = dict(legacy_event)
    corrupt_event["occurred_at"] = None
    corrupt_event_result = HarnessLegacyEventReader().read_or_quarantine(
        corrupt_event,
        stream_sequence=1,
        history_evidence_ref=history_ref,
    )
    invalid_payload_event = dict(legacy_event)
    invalid_payload_event["payload"] = {"raw_payload": "not-catalog-validated"}
    invalid_payload_result = HarnessLegacyEventReader().read_or_quarantine(
        invalid_payload_event,
        stream_sequence=1,
        history_evidence_ref=history_ref,
    )
    corrupt_state = dict(legacy_state)
    corrupt_steps = [dict(item) for item in legacy_state["step_states"]]
    corrupt_steps[0]["attempts"] = -1
    corrupt_state["step_states"] = corrupt_steps
    corrupt_state_result = HarnessGraphStateReader().read_or_quarantine(
        corrupt_state,
        rebuilt_state=graph_state,
        history_evidence_ref=history_ref,
    )

    assert missing_state_evidence.quarantine_reason == (
        "graph_history_evidence_missing"
    )
    assert missing_event_evidence.quarantine_reason == (
        "graph_history_evidence_missing"
    )
    assert corrupt_event_result.quarantine_reason == "invalid_legacy_event"
    assert invalid_payload_result.quarantine_reason == (
        "legacy_event_schema_validation_failed"
    )
    assert corrupt_state_result.quarantine_reason == "invalid_legacy_graph_state"


def test_legacy_checkpoint_corruption_and_missing_evidence_are_quarantined() -> None:
    _, event_port, run_spec, result = _completed_run("run-v1-checkpoint-quarantine")
    graph_state = event_port.recover_graph(run_spec.run_id).state
    assert graph_state is not None
    legacy = HarnessCheckpoint(
        checkpoint_id="legacy-quarantine",
        run_id=run_spec.run_id,
        state=result.state,
        created_at=_NOW,
    )
    value = {"schema_version": LEGACY_CHECKPOINT_SCHEMA, **legacy.to_dict()}
    reader = HarnessGraphCheckpointReader()

    missing = reader.read_or_quarantine(
        value,
        rebuilt_state=graph_state,
        last_event_sequence=graph_state.last_event_sequence,
    )
    corrupt = dict(value)
    corrupt["checksum"] = checksum_for("corrupt-legacy-checkpoint")
    corrupt_result = reader.read_or_quarantine(
        corrupt,
        rebuilt_state=graph_state,
        last_event_sequence=graph_state.last_event_sequence,
        history_evidence_ref=checksum_for("verified-v1-history"),
    )

    assert missing.quarantine_reason == "graph_history_evidence_missing"
    assert corrupt_result.quarantine_reason == "legacy_checkpoint_checksum_mismatch"


def test_verify_history_never_uses_live_scheduler_workers_or_gates() -> None:
    control_plane, event_port, run_spec, expected = _completed_run(
        "run-no-live-replay-fallback"
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("live replay fallback was invoked")

    control_plane.worker_registry = {"first": forbidden, "second": forbidden}
    control_plane.scheduler = forbidden  # type: ignore[assignment]
    control_plane.plan_gates = (forbidden,)  # type: ignore[assignment]
    control_plane.verify_gates = (forbidden,)  # type: ignore[assignment]
    event_port.accept_activity = forbidden  # type: ignore[method-assign]
    event_count = len(event_port.events)

    report = control_plane.verify_graph_history(run_spec)

    assert expected.graph_state is not None
    assert report.state == expected.graph_state
    assert len(event_port.events) == event_count


def test_durable_verify_reads_activity_history_without_accepting_new_work() -> None:
    from tests.framework.harness.control_plane.test_durable_event_boundary import (
        CanonicalRecordingRuntime,
        _durable_port,
    )

    run_spec = _linear_run_spec("run-durable-read-only-replay")
    runtime = CanonicalRecordingRuntime()
    event_port = _durable_port(runtime)
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"first": True},
            ),
            "second": lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"second": True},
            ),
        },
    )
    expected = control_plane.run(run_spec)
    activity_store = event_port._activity_store
    assert activity_store is not None
    record_count = len(activity_store.records)
    payload_count = len(activity_store.payloads)
    event_count = len(runtime.events)

    class _ForbiddenRecorder:
        @staticmethod
        def accept(**_kwargs):
            raise AssertionError("VERIFY_HISTORY accepted new activity work")

    event_port._activity_recorder = _ForbiddenRecorder()
    report = control_plane.verify_graph_history(run_spec)

    assert expected.graph_state is not None
    assert report.state == expected.graph_state
    assert len(activity_store.records) == record_count
    assert len(activity_store.payloads) == payload_count
    assert len(runtime.events) == event_count


def test_logical_graph_transition_schemas_are_reference_only_and_registered() -> None:
    catalog = default_event_schema_catalog()
    checksum = checksum_for("transition")
    payload = {
        "transition_type": "activate_node",
        "graph_checksum": checksum,
        "projection_checksum": checksum,
        "cause_checksum": checksum,
        "node_instance_id": "node-instance-1",
        "attempt": 1,
        "evidence_refs": [checksum],
        "payload_refs": {"output": checksum},
        "diagnostic_refs": [],
    }

    for event_type, schema in HARNESS_GRAPH_TRANSITION_EVENT_SCHEMAS.items():
        validated = catalog.validate(
            event_type,
            schema,
            {"schema_version": schema, **payload},
        )
        assert validated["schema_version"] == schema
        assert "payload" not in validated

    legacy = DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.require_readable(
        HarnessGraphContractKind.GRAPH_EVENT,
        LEGACY_EVENT_SCHEMA,
    )
    assert LEGACY_EVENT_SCHEMA in legacy.legacy_upcast_sources
    with pytest.raises(HarnessValidationError) as captured:
        DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.require_executable(
            HarnessGraphContractKind.GRAPH_EVENT,
            LEGACY_EVENT_SCHEMA,
        )
    assert captured.value.code == "graph_schema_not_executable"


def test_parallel_any_winner_replays_from_recorded_sequence() -> None:
    from tests.framework.harness.control_plane.test_parallel_graph_control_plane import (
        _control_plane,
        _parallel_any_run_spec,
    )

    run_spec = _parallel_any_run_spec("run-replay-parallel-any")
    event_port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port, [])
    result = control_plane.run(run_spec)

    assert result.graph_state is not None
    winner = result.graph_state.join_states[0].winner_branch_id
    report = control_plane.verify_graph_history(run_spec)

    assert winner == "left-branch"
    assert report.state.join_states[0].winner_branch_id == winner
    assert report.projection_checksum == result.graph_state.projection_checksum


def test_timer_wait_wake_replays_without_reading_current_clock() -> None:
    from tests.framework.harness.control_plane.test_wait_graph_control_plane import (
        _CREATED_AT,
        _control_plane,
        _scope,
        _wait_run_spec,
    )
    from framework.harness.waits.models import HarnessWaitTimerWakeRecord

    run_spec = _wait_run_spec("run-replay-timer-wait", wait_kind="timer")
    event_port = InMemoryHarnessEventPort()
    control_plane = _control_plane(event_port)
    waiting = control_plane.run(run_spec).graph_state
    assert waiting is not None
    registration = waiting.wait_registrations[0]
    control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitTimerWakeRecord(
            _scope(run_spec.run_id, registration),
            registration.deadline_ref,
            checksum_for("recorded-timer-wake"),
            0,
        ),
        occurred_at=_CREATED_AT,
    )
    completed = control_plane.recover_and_run(run_spec)

    assert completed.graph_state is not None
    report = control_plane.verify_graph_history(run_spec)
    assert report.state.wait_registrations[0].status.value == "resumed"
    assert report.projection_checksum == completed.graph_state.projection_checksum


def test_completed_compensation_replays_from_committed_effect_evidence() -> None:
    from tests.framework.harness.control_plane.test_compensation_entry_durability import (
        _parallel_compensation_fixture,
    )
    from framework.harness.workflow.validation import (
        HarnessGraphPreflight,
        HarnessGraphPreflightPolicy,
    )

    fixture = _parallel_compensation_fixture("run-replay-completed-compensation")
    fixture.control_plane.graph_preflight = HarnessGraphPreflight(
        policy=HarnessGraphPreflightPolicy(
            max_node_activations=30,
            max_active_nodes=8,
            max_parallelism=1,
            max_compensations=4,
        )
    )
    result = fixture.control_plane.run(fixture.run_spec)

    assert result.graph_state is not None
    assert len(result.graph_state.compensation_stack) == 1
    assert result.graph_state.compensation_stack[0].status.value == "succeeded"
    report = fixture.control_plane.verify_graph_history(fixture.run_spec)

    assert report.state.compensation_stack == result.graph_state.compensation_stack
    assert report.projection_checksum == result.graph_state.projection_checksum


def _completed_run(
    run_id: str,
) -> tuple[
    HarnessControlPlane,
    InMemoryHarnessEventPort,
    HarnessRunSpec,
    HarnessRunResult,
]:
    run_spec = _linear_run_spec(run_id)
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "first": lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"first": True},
            ),
            "second": lambda _task: HarnessWorkerResult(
                "succeeded",
                output={"second": True},
            ),
        },
    )
    result = control_plane.run(run_spec)
    return control_plane, event_port, run_spec, result


def _linear_run_spec(run_id: str) -> HarnessRunSpec:
    workflow = HarnessWorkflowSpec(
        workflow_id=f"workflow-{run_id}",
        steps=(
            HarnessStepSpec("first", "script", output_key="first_output"),
            HarnessStepSpec("second", "script", output_key="second_output"),
        ),
        entry_step_id="first",
        graph=HarnessGraphSpec(
            f"graph-{run_id}",
            Sequence((StepRef("first"), StepRef("second"))),
        ),
    )
    return HarnessRunSpec(run_id, workflow, created_at=_NOW)
