from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.events.errors import EventReplayMismatchError, EventStoreCorruptionError
from framework.harness.control_plane.policy import HarnessBudget
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
)
from framework.harness.control_plane.transition import (
    HarnessStateProjection,
    HarnessStateProjector,
    HarnessTransitionCommitted,
    HarnessTransitionKind,
)
from framework.harness.control_plane.transitions import transition_run
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 7, 16, 9, 30, tzinfo=UTC)


def _run_spec(*, workflow_version: str = "1") -> HarnessRunSpec:
    return HarnessRunSpec(
        run_id="run-transition",
        workflow=HarnessWorkflowSpec(
            workflow_id="transition-workflow",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    output_key="answer",
                ),
            ),
            entry_step_id="collect",
            metadata={"version": workflow_version},
        ),
        inputs={"source_ref": "source://paper"},
        budget=HarnessBudget.safe_default(),
        created_at=NOW,
    )


def _initial_state(run_spec: HarnessRunSpec) -> HarnessState:
    state = HarnessState.initial(run_spec)
    return replace(
        state,
        updated_at=NOW,
        step_states=tuple(replace(step, updated_at=NOW) for step in state.step_states),
    )


def test_projector_rebuilds_state_from_contiguous_versioned_transitions() -> None:
    run_spec = _run_spec()
    initial = _initial_state(run_spec)
    created = HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind=HarnessTransitionKind.INITIALIZE,
        occurred_at=NOW,
    )
    running = transition_run(initial, "running")
    started = HarnessTransitionCommitted.create(
        previous=initial,
        state=running,
        from_version=1,
        expected_last_sequence=3,
        transition_kind=HarnessTransitionKind.RUN_START,
        occurred_at=NOW + timedelta(microseconds=1),
    )

    projected = HarnessStateProjector().project(run_spec, (created, started))

    assert projected.state is not None
    assert projected.state.status.value == "running"
    assert projected.state_version == 2
    assert projected.state_checksum == started.after_state_checksum
    assert projected.last_transition_id == started.transition_id


def test_transition_identity_excludes_wall_clock_and_stream_position() -> None:
    run_spec = _run_spec()
    state = _initial_state(run_spec)
    first = HarnessTransitionCommitted.create(
        previous=None,
        state=state,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    retry = HarnessTransitionCommitted.create(
        previous=None,
        state=state,
        from_version=0,
        expected_last_sequence=8,
        transition_kind="initialize",
        occurred_at=NOW + timedelta(minutes=1),
    )

    assert retry.transition_id == first.transition_id

    tenant_a = HarnessTransitionCommitted.create(
        previous=None,
        state=state,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
        identity_scope_ref=checksum_for("tenant-a"),
    )
    tenant_a_retry = HarnessTransitionCommitted.create(
        previous=None,
        state=state,
        from_version=0,
        expected_last_sequence=99,
        transition_kind="initialize",
        occurred_at=NOW + timedelta(hours=1),
        identity_scope_ref=checksum_for("tenant-a"),
    )
    tenant_b = HarnessTransitionCommitted.create(
        previous=None,
        state=state,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
        identity_scope_ref=checksum_for("tenant-b"),
    )

    assert tenant_a.transition_id.startswith("harness-transition-v2:")
    assert tenant_a_retry.transition_id == tenant_a.transition_id
    assert tenant_b.transition_id != tenant_a.transition_id


def test_state_projection_never_inlines_worker_output_or_free_form_errors() -> None:
    secret = "sk-transition-secret"
    run_spec = _run_spec()
    initial = _initial_state(run_spec)
    step = replace(
        initial.step_states[0],
        output_ref="answer",
        error=f"provider rejected {secret}",
        metadata={
            "activity_id": "harness-activity:one",
            "activity_result_event_id": "harness-event:one",
            "worker_result": {"output": {"api_key": secret}},
        },
    )
    state = replace(
        initial,
        step_states=(step,),
        metadata={
            "outputs": {"answer": secret},
            "claims": [secret],
            "terminal_reason": secret,
        },
    )
    serialized = stable_json_dumps(HarnessStateProjection.from_state(state).to_dict())

    assert secret not in serialized
    assert "worker_result_ref" in serialized
    assert "activity_result_event_id" in serialized


def test_projector_rejects_version_gap_before_applying_transition() -> None:
    run_spec = _run_spec()
    initial = _initial_state(run_spec)
    transition = HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    gap = replace(
        transition,
        from_version=1,
        state_version=2,
        transition_id=None,
    )

    with pytest.raises(EventReplayMismatchError, match="not contiguous"):
        HarnessStateProjector().project(run_spec, (gap,))


def test_projector_rejects_checksum_and_workflow_mismatch() -> None:
    run_spec = _run_spec()
    initial = _initial_state(run_spec)
    transition = HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    corrupt = replace(
        transition,
        after_state_checksum=checksum_for({"tampered": True}),
        transition_id=None,
    )

    with pytest.raises(EventStoreCorruptionError, match="after-state checksum"):
        HarnessStateProjector().project(run_spec, (corrupt,))
    with pytest.raises(EventReplayMismatchError, match="run specification checksum"):
        HarnessStateProjector().project(_run_spec(workflow_version="2"), (transition,))


def test_projector_rejects_self_consistent_but_illegal_state_transition() -> None:
    run_spec = _run_spec()
    initial = _initial_state(run_spec)
    initialized = HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    illegal_state = replace(
        initial,
        status=HarnessRunStatus.SUCCEEDED,
        updated_at=NOW + timedelta(microseconds=1),
    )
    projection = HarnessStateProjection.from_state(illegal_state)
    illegal = HarnessTransitionCommitted(
        run_id=run_spec.run_id,
        transition_kind="success",
        from_version=1,
        state_version=2,
        expected_last_sequence=1,
        state=projection,
        before_state_checksum=initialized.after_state_checksum,
        after_state_checksum=projection.checksum,
        occurred_at=illegal_state.updated_at,
    )

    with pytest.raises(EventReplayMismatchError, match="control-plane semantics"):
        HarnessStateProjector().project(run_spec, (initialized, illegal))


def test_projection_normalizes_invalid_historical_times_to_typed_corruption() -> None:
    run_spec = _run_spec()
    projection = HarnessStateProjection.from_state(_initial_state(run_spec))
    invalid_state_time = projection.to_dict()
    invalid_state_time["updated_at"] = "not-a-time"

    with pytest.raises(EventStoreCorruptionError, match="updated_at"):
        HarnessStateProjection.from_dict(invalid_state_time)

    invalid_step_time = projection.to_dict()
    invalid_step_time["step_states"][0]["updated_at"] = "not-a-time"
    parsed = HarnessStateProjection.from_dict(invalid_step_time)
    with pytest.raises(EventStoreCorruptionError, match="step updated_at"):
        parsed.restore(run_spec)
