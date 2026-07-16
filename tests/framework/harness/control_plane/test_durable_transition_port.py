from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.errors import EventReplayMismatchError, EventStoreUnavailableError
from framework.events.runtime.models import StreamReadRequest
from framework.events.runtime.publisher import EventRuntime
from framework.events.schema import default_event_schema_catalog
from framework.harness.control_plane.durable_events import (
    DurableHarnessTransitionPort,
    HarnessEventCanonicalAdapter,
)
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.state import HarnessRunSpec, HarnessState
from framework.harness.control_plane.transitions import transition_run, transition_step
from framework.harness.control_plane.transition import HarnessTransitionCommitted
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 16, 10, 30, tzinfo=UTC)


class _CommitThenFailRuntime:
    def __init__(self, runtime: EventRuntime) -> None:
        self.runtime = runtime
        self.failed = False

    def publish(self, event, *, expected_last_sequence=None, unit_of_work=None):
        stored = self.runtime.publish(
            event,
            expected_last_sequence=expected_last_sequence,
            unit_of_work=unit_of_work,
        )
        if event.event_type == "harness_transition_committed" and not self.failed:
            self.failed = True
            raise EventStoreUnavailableError("commit response was lost")
        return stored


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


def _initial(run_spec: HarnessRunSpec) -> HarnessState:
    state = HarnessState.initial(run_spec)
    return replace(
        state,
        updated_at=NOW,
        step_states=tuple(replace(step, updated_at=NOW) for step in state.step_states),
    )


def _runtime(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite3")
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    return store, runtime


def test_durable_transition_port_recovers_state_from_ordered_canonical_history(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    initial = _initial(run_spec)
    port = DurableHarnessTransitionPort(runtime, store)
    created = port.commit_transition(
        None,
        initial,
        from_version=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    port.record(
        HarnessEvent(
            event_type=HarnessEventType.RUN_CREATED,
            run_id=run_spec.run_id,
            occurred_at=NOW,
        )
    )
    running = replace(transition_run(initial, "running"), updated_at=NOW + timedelta(microseconds=1))
    started = port.commit_transition(
        initial,
        running,
        from_version=1,
        transition_kind="run_start",
        occurred_at=running.updated_at,
    )

    recovered_port = DurableHarnessTransitionPort(runtime, store)
    recovered = recovered_port.recover(run_spec)
    log_entries = recovered_port.entries_for_run(run_spec.run_id)

    assert recovered.state is not None
    assert recovered.state.status.value == "running"
    assert recovered.state_version == 2
    assert recovered.expected_last_sequence == 3
    assert [item.state_version for item in recovered.transitions] == [1, 2]
    assert [item.stream_sequence for item in recovered.transitions] == [1, 3]
    assert [entry.stream_sequence for entry in log_entries] == [1, 2, 3]
    assert log_entries[-1].status_after == "running"
    assert created.transition.state_version == 1
    assert started.transition.state_version == 2


def test_uncertain_transition_commit_is_resolved_by_deterministic_identity(
    tmp_path,
) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    initial = _initial(run_spec)
    failing = DurableHarnessTransitionPort(_CommitThenFailRuntime(runtime), store)

    with pytest.raises(EventStoreUnavailableError, match="response was lost"):
        failing.commit_transition(
            None,
            initial,
            from_version=0,
            transition_kind="initialize",
            occurred_at=NOW,
        )

    recovered = DurableHarnessTransitionPort(runtime, store).commit_transition(
        None,
        initial,
        from_version=0,
        transition_kind="initialize",
        occurred_at=NOW + timedelta(minutes=1),
    )
    page = store.read_stream(
        StreamReadRequest(stream_id=f"run:{run_spec.run_id}", limit=20)
    )

    assert recovered.transition.stream_sequence == 1
    assert len(page.events) == 1


def test_stale_state_version_fails_before_a_second_transition_append(tmp_path) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    initial = _initial(run_spec)
    port = DurableHarnessTransitionPort(runtime, store)
    port.commit_transition(
        None,
        initial,
        from_version=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    running = replace(transition_run(initial, "running"), updated_at=NOW + timedelta(microseconds=1))
    port.commit_transition(
        initial,
        running,
        from_version=1,
        transition_kind="run_start",
        occurred_at=running.updated_at,
    )
    planning_time = running.updated_at + timedelta(microseconds=1)
    planning = transition_run(running, "planning", at=planning_time)
    planning = transition_step(
        planning,
        run_spec.workflow.entry_step_id,
        "planning",
        turn_increment=1,
        at=planning_time,
    )

    with pytest.raises(EventReplayMismatchError, match="stale state version"):
        port.commit_transition(
            running,
            planning,
            from_version=1,
            transition_kind="plan_entry",
            occurred_at=planning_time,
        )

    page = store.read_stream(
        StreamReadRequest(stream_id=f"run:{run_spec.run_id}", limit=20)
    )
    assert len(page.events) == 2


def test_tenant_scoped_retry_recovers_legacy_transition_identity(tmp_path) -> None:
    store, runtime = _runtime(tmp_path)
    run_spec = _run_spec()
    initial = _initial(run_spec)
    legacy = HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )
    legacy_request = HarnessEventCanonicalAdapter().to_transition_publish_request(
        legacy
    )
    stored = runtime.publish(
        replace(legacy_request, tenant_id="tenant-a"),
        expected_last_sequence=0,
    )
    port = DurableHarnessTransitionPort(
        runtime,
        store,
        adapter=HarnessEventCanonicalAdapter(tenant_id="tenant-a"),
    )

    recovered = port.commit_transition(
        None,
        initial,
        from_version=0,
        transition_kind="initialize",
        occurred_at=NOW + timedelta(minutes=1),
    )
    page = store.read_stream(
        StreamReadRequest(
            stream_id=f"run:{run_spec.run_id}",
            tenant_id="tenant-a",
            limit=20,
        )
    )

    assert recovered.transition.transition_id == legacy.transition_id
    assert recovered.stored_event == stored
    assert len(page.events) == 1
