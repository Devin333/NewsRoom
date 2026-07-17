from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from framework.artifacts import ArtifactManager
from framework.events import EventRuntime, default_event_schema_catalog
from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.checkpoint.durable import durable_envelope_from_checkpoint
from framework.workflow.checkpoint.recovery import verified_checkpoint_recovery_cursor
from framework.workflow.checkpoint.resume import ResumeMode, WorkflowResumeRequest
from framework.workflow.checkpoint.store import LocalJsonCheckpointStore
from framework.workflow.runners.base import (
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
)
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.checkpoint_coordinator import CheckpointCoordinator
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.execution_loop import WorkflowExecutionLoop
from framework.workflow.runtime.manifest_updater import ManifestUpdater
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runtime.runtime_event_bridge import RuntimeEventBridge
from framework.workflow.runtime.state_machine import WorkflowStateMachine
from infrastructure.storage.events.sqlite import SQLiteEventStore


class _PauseRunner:
    def __init__(self, step_type: StepType) -> None:
        self.capability = StepRunnerCapability(
            step_type=step_type,
            runner_id=f"test.pause.{step_type.value}",
            version="1",
            supports_checkpoint=True,
            supports_resume=True,
            supports_timeout=True,
            supports_retry=False,
            side_effect_level=StepRunnerSideEffectLevel.NONE,
        )

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == self.capability.step_type

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        raise AssertionError("pause recovery tests invoke the transition directly")


class _FaultInjectingStore:
    def __init__(self, store: SQLiteEventStore) -> None:
        self.store = store
        self.fail_on_append: int | None = None

    def unit_of_work(self) -> _FaultInjectingUnitOfWork:
        return _FaultInjectingUnitOfWork(self, self.store.unit_of_work())


class _FaultInjectingUnitOfWork:
    def __init__(self, owner: _FaultInjectingStore, inner: Any) -> None:
        self._owner = owner
        self._inner = inner
        self._append_count = 0

    def __enter__(self) -> _FaultInjectingUnitOfWork:
        self._inner.__enter__()
        return self

    def append_event(
        self,
        event: Any,
        *,
        expected_last_sequence: int | None = None,
    ) -> Any:
        self._append_count += 1
        if self._owner.fail_on_append == self._append_count:
            raise OSError(f"injected append failure {self._append_count}")
        return self._inner.append_event(
            event,
            expected_last_sequence=expected_last_sequence,
        )

    def settle_delivery(self, settlement: Any) -> Any:
        return self._inner.settle_delivery(settlement)

    def commit(self) -> None:
        self._inner.commit()

    def rollback(self) -> None:
        self._inner.rollback()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        return self._inner.__exit__(exc_type, exc, traceback)


class _CrashAfterCommittedBatch:
    def __init__(self, recorder: Any) -> None:
        self._recorder = recorder

    def emit_batch(self, facts: Any) -> Any:
        self._recorder.emit_batch(facts)
        raise RuntimeError("simulated crash after transition commit")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._recorder, name)


class _CountingReader:
    def __init__(self, reader: Any) -> None:
        self._reader = reader
        self.read_limits: list[int] = []

    def read_stream(self, request: Any) -> Any:
        self.read_limits.append(request.limit)
        return self._reader.read_stream(request)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._reader, name)


@pytest.mark.parametrize("fail_on_append", [2, 3])
def test_pause_batch_append_failure_leaves_no_partial_facts(
    tmp_path: Path,
    fail_on_append: int,
) -> None:
    context, loop, event_store, fault_store, checkpoint_store, step, outcome = (
        _pause_context(tmp_path, step_type=StepType.HUMAN_REVIEW)
    )
    fault_store.fail_on_append = fail_on_append

    with pytest.raises(OSError, match=f"injected append failure {fail_on_append}"):
        loop._handle_pause(context, step, outcome)

    assert context.status == WorkflowStatus.RUNNING
    assert [event.event_type for event in context.event_emitter.list_events()] == [
        "workflow_started"
    ]
    checkpoint = checkpoint_store.get_latest_checkpoint(context.run_id)
    assert checkpoint is not None
    assert checkpoint.last_durable_stream_sequence == 1
    assert event_store.get_stream_high_watermark(context.event_emitter.stream_id) == 1


def test_recovery_reconciles_commit_before_local_status_assignment_crash(
    tmp_path: Path,
) -> None:
    context, loop, _event_store, _fault_store, checkpoint_store, step, outcome = (
        _pause_context(tmp_path, step_type=StepType.HUMAN_REVIEW)
    )
    context.recorder = _CrashAfterCommittedBatch(context.recorder)

    with pytest.raises(RuntimeError, match="simulated crash after transition commit"):
        loop._handle_pause(context, step, outcome)

    assert context.status == WorkflowStatus.RUNNING
    events = context.event_emitter.list_events()
    assert [event.event_type for event in events[-6:]] == [
        "step_paused",
        "checkpoint_created",
        "human_review_requested",
        "human_review_paused",
        "workflow_paused",
        "workflow_transition_committed",
    ]
    checkpoint = checkpoint_store.get_latest_checkpoint(context.run_id)
    assert checkpoint is not None
    cursor = verified_checkpoint_recovery_cursor(
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        reader=context.event_emitter.reader,
    )
    transition = events[-1]
    assert cursor.after_sequence == checkpoint.last_durable_stream_sequence
    assert cursor.reconciled_through_sequence == transition.stream_sequence
    assert cursor.reconciled_event_id == transition.event_id
    assert cursor.recovered_transition_type == "request_human_review"
    assert cursor.recovered_workflow_status == "waiting_for_human"
    assert not cursor.should_apply(transition.stream_sequence)

    with pytest.raises(ValueError, match="requires a human decision or approval"):
        WorkflowResumeRequest(
            mode=ResumeMode.EXACT,
            checkpoint=durable_envelope_from_checkpoint(checkpoint),
            recovery_cursor=cursor,
        )
    authorized = WorkflowResumeRequest(
        mode=ResumeMode.AFTER_HUMAN_REVIEW,
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        recovery_cursor=cursor,
        human_decision={
            "decision": "approved",
            "actor_id": "reviewer-1",
            "request_id": "review-1",
        },
    )
    assert authorized.mode == ResumeMode.AFTER_HUMAN_REVIEW

    mismatched = replace(checkpoint, current_step_ids=["different-step"])
    with pytest.raises(ValueError, match="transition step_id does not match checkpoint"):
        verified_checkpoint_recovery_cursor(
            checkpoint=durable_envelope_from_checkpoint(mismatched),
            reader=context.event_emitter.reader,
        )


def test_plain_pause_commits_and_recovers_one_authoritative_batch(
    tmp_path: Path,
) -> None:
    context, loop, _event_store, _fault_store, checkpoint_store, step, outcome = (
        _pause_context(tmp_path, step_type=StepType.FUNCTION)
    )

    loop._handle_pause(context, step, outcome)

    assert context.status == WorkflowStatus.PAUSED
    events = context.event_emitter.list_events()
    assert [event.event_type for event in events[-4:]] == [
        "step_paused",
        "checkpoint_created",
        "workflow_paused",
        "workflow_transition_committed",
    ]
    checkpoint = checkpoint_store.get_latest_checkpoint(context.run_id)
    assert checkpoint is not None
    cursor = verified_checkpoint_recovery_cursor(
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        reader=context.event_emitter.reader,
    )
    assert cursor.reconciled_through_sequence == events[-1].stream_sequence
    assert cursor.recovered_transition_type == "pause"
    assert cursor.recovered_workflow_status == "paused"
    exact = WorkflowResumeRequest(
        mode=ResumeMode.EXACT,
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        recovery_cursor=cursor,
    )
    assert exact.mode == ResumeMode.EXACT


def test_ordinary_checkpoint_with_later_events_keeps_original_cursor(
    tmp_path: Path,
) -> None:
    context, _loop, _event_store, _fault_store, checkpoint_store, step, _outcome = (
        _pause_context(tmp_path, step_type=StepType.FUNCTION)
    )
    checkpoint_id = CheckpointCoordinator(
        checkpoint_store=checkpoint_store
    ).write_checkpoint(
        run_id=context.run_id,
        workflow=context.workflow,
        profile=context.profile,
        current_step_ids=[step.step_id],
        buffer=context.buffer,
        step_results=context.step_results,
        path=context.path,
        recorder=context.recorder,
        trace_context=context.step_trace_contexts[step.step_id],
    )
    checkpoint_created = context.recorder.last_accepted_event
    later = None
    for _index in range(100):
        later = context.recorder.emit(
            "step_succeeded",
            {"step_id": step.step_id, "outputs": []},
            trace_context=context.step_trace_contexts[step.step_id],
        )
    checkpoint = checkpoint_store.get_checkpoint(context.run_id, checkpoint_id)
    assert checkpoint is not None
    reader = _CountingReader(context.event_emitter.reader)

    cursor = verified_checkpoint_recovery_cursor(
        checkpoint=durable_envelope_from_checkpoint(checkpoint),
        reader=reader,
    )

    assert cursor.reconciled_through_sequence is None
    assert cursor.effective_after_sequence == checkpoint.last_durable_stream_sequence
    assert checkpoint_created is not None
    assert later is not None
    assert cursor.should_apply(checkpoint_created.stream_sequence)
    assert cursor.should_apply(later.sequence)
    assert reader.read_limits == [6]


def _pause_context(
    tmp_path: Path,
    *,
    step_type: StepType,
) -> tuple[
    Any,
    WorkflowExecutionLoop,
    SQLiteEventStore,
    _FaultInjectingStore,
    LocalJsonCheckpointStore,
    StepSpec,
    StepOutcome,
]:
    run_id = f"run-{step_type.value.replace('_', '-')}-{tmp_path.name}"
    write_keys = ["human_review_request"] if step_type == StepType.HUMAN_REVIEW else ["ok"]
    step = StepSpec(step_id="s1", step_type=step_type, write_keys=write_keys)
    workflow = WorkflowSpec(
        workflow_id="wf-atomic-pause",
        name="Atomic pause",
        version="1",
        start_step_id=step.step_id,
        steps=[step],
        terminal_step_ids=[step.step_id],
    )
    registry = StepRunnerRegistry()
    registry.register(step_type, _PauseRunner(step_type))
    event_store = SQLiteEventStore(tmp_path / "events.sqlite3")
    fault_store = _FaultInjectingStore(event_store)
    catalog = default_event_schema_catalog()
    context = build_execution_context(
        workflow=workflow,
        request={},
        profile="test",
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        step_runner_registry=registry,
        event_runtime=EventRuntime(store=fault_store, schema_catalog=catalog),
        event_reader=event_store,
        event_schema_catalog=catalog,
        started_monotonic=0.0,
        run_id=run_id,
    )
    context.recorder.emit(
        "workflow_started",
        {"workflow_version": workflow.version, "profile": context.profile},
        trace_context=context.trace_context,
    )
    context.status = WorkflowStatus.RUNNING
    context.path = [step.step_id]
    context.current_step_ids = []
    context.step_trace_contexts[step.step_id] = context.trace_context.child(
        step_id=step.step_id
    )
    outputs = (
        {"human_review_request": {"request_id": "review-1"}}
        if step_type == StepType.HUMAN_REVIEW
        else {}
    )
    outcome = StepOutcome(status=StepStatus.PAUSED, outputs=outputs)
    context.step_results[step.step_id] = outcome
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    loop = WorkflowExecutionLoop(
        state_machine=WorkflowStateMachine(),
        routing_engine=object(),
        step_invoker=object(),
        checkpoint_coordinator=CheckpointCoordinator(
            checkpoint_store=checkpoint_store
        ),
        event_bridge=RuntimeEventBridge(),
        manifest_updater=ManifestUpdater(
            artifact_manager=ArtifactManager(tmp_path / "runs"),
            run_id=context.run_id,
            manifest=context.manifest,
        ),
        is_run_cancelled=lambda _run_id: False,
    )
    return context, loop, event_store, fault_store, checkpoint_store, step, outcome
