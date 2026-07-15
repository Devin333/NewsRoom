from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import EventCandidate, StoredEvent, assert_same_event_identity
from framework.events.errors import EventStoreUnavailableError
from framework.events.runtime.publisher import EventPublishRequest
from framework.events.schema import EventSecurityProjector, default_event_schema_catalog
from framework.harness import (
    DurableHarnessEventPort,
    HarnessBudget,
    HarnessControlPlane,
    HarnessDecisionType,
    HarnessEvent,
    HarnessEventCanonicalAdapter,
    HarnessEventType,
    HarnessGateResult,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessRetryPolicy,
    HarnessReplayReader,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    event_log_entry_from_stored_event,
)
from framework.shared.json import stable_json_dumps


NOW = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)


class CanonicalRecordingRuntime:
    def __init__(
        self,
        *,
        fail_before: Callable[[EventPublishRequest], bool] | None = None,
        fail_after: Callable[[EventPublishRequest], bool] | None = None,
    ) -> None:
        self.fail_before = fail_before or (lambda request: False)
        self.fail_after = fail_after or (lambda request: False)
        self.attempts: list[EventPublishRequest] = []
        self.events: list[StoredEvent] = []
        self._by_id: dict[str, StoredEvent] = {}

    def publish(self, event: EventPublishRequest, *, unit_of_work=None) -> StoredEvent:
        assert unit_of_work is None
        self.attempts.append(event)
        if self.fail_before(event):
            raise EventStoreUnavailableError("durable Harness store is unavailable")
        candidate = EventCandidate(
            event_id=event.event_id,
            event_type=event.event_type,
            data_schema=event.data_schema,
            source=event.source,
            subject=event.subject,
            occurred_at=event.occurred_at,
            stream_id=event.stream_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            business_context=event.business_context,
            producer=event.producer,
            trace=event.trace,
            tenant_id=event.tenant_id,
            security_classification=event.security_classification,
            content_type=event.content_type,
            payload=event.payload,
            payload_ref=event.payload_ref,
            extensions=event.extensions,
        )
        existing = self._by_id.get(candidate.event_id)
        if existing is not None:
            assert_same_event_identity(existing, candidate)
            return existing
        stored = StoredEvent(
            candidate=candidate,
            observed_at=NOW + timedelta(microseconds=len(self.events)),
            stream_sequence=len(self.events) + 1,
        )
        self.events.append(stored)
        self._by_id[stored.event_id] = stored
        if self.fail_after(event):
            raise EventStoreUnavailableError("commit outcome was uncertain")
        return stored


class CountingGate:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, context) -> HarnessGateResult:
        self.calls += 1
        return HarnessGateResult(gate_name="counting", passed=True)


def test_control_plane_requires_an_explicit_event_port() -> None:
    with pytest.raises(HarnessValidationError, match="event_port is required"):
        HarnessControlPlane()


def test_typed_harness_event_detaches_and_freezes_nested_transition_content() -> None:
    payload = {"status": "running", "nested": {"attempt": 1}}
    metadata = {"status_before": "created", "labels": ["durable"]}
    event = HarnessEvent(
        event_type=HarnessEventType.RUN_STATE_CHANGED,
        run_id="run-immutable",
        payload=payload,
        metadata=metadata,
        occurred_at=NOW,
    )

    payload["nested"]["attempt"] = 99
    metadata["labels"].append("mutated")

    assert event.payload["nested"]["attempt"] == 1
    assert event.metadata["labels"] == ("durable",)
    with pytest.raises(TypeError):
        event.payload["status"] = "failed"  # type: ignore[index]


def test_typed_harness_event_roundtrips_through_canonical_commit_and_log_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    source = HarnessEvent(
        event_type=HarnessEventType.RUN_STATE_CHANGED,
        run_id="run-durable",
        step_id="collect",
        payload={"status": "running"},
        metadata={
            "status_before": "created",
            "status_after": "running",
            "transition_kind": "run_start",
        },
        occurred_at=NOW,
    )

    projected = port.record(source)

    assert projected.event_id == source.event_id
    assert projected.run_id == source.run_id
    assert projected.step_id == source.step_id
    assert projected.payload == {
        "projection_schema": "harness-safe-summary/v1",
        "status": "running",
    }
    assert len(runtime.events) == 1
    stored = runtime.events[0]
    assert stored.stream_id == "run:run-durable"
    assert stored.stream_sequence == 1
    assert stored.business_context.run_id == "run-durable"
    assert stored.business_context.step_id == "collect"
    entry = port.event_log_entries[0]
    assert entry.event_id == stored.event_id
    assert entry.status_before == "created"
    assert entry.status_after == "running"
    assert entry.stream_sequence == 1
    assert entry.record_checksum == stored.record_checksum


def test_worker_activity_projection_persists_refs_without_raw_secret_content() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    secret = "sk-harness-raw-secret"
    event = HarnessEvent(
        event_type=HarnessEventType.WORKER_RESULT_RECORDED,
        run_id="run-redacted-worker",
        step_id="collect",
        payload={
            "status": "failed",
            "output": {"api_key": secret},
            "artifacts": [],
            "diagnostics": {"authorization": secret},
            "metrics": {"attempts": 1},
            "error": f"worker rejected {secret}",
        },
        metadata={
            "credential_ref": secret,
            "operator_note": f"do not persist {secret}",
            "safe_refs": [secret],
        },
        occurred_at=NOW,
    )

    port.record(event)

    serialized = stable_json_dumps(runtime.events[0].to_dict())
    assert secret not in serialized
    assert runtime.events[0].payload["output_ref"].startswith("sha256:")
    assert runtime.events[0].payload["diagnostics_ref"].startswith("sha256:")
    assert runtime.events[0].payload["error_ref"].startswith("sha256:")
    assert runtime.events[0].extensions["harness"]["metadata"]["omitted_metadata_count"] == 3
    assert runtime.events[0].extensions["harness"]["metadata"]["omitted_metadata_ref"].startswith(
        "sha256:"
    )


def test_default_catalog_accepts_adapter_summaries_without_raw_worker_or_gate_content() -> None:
    secret = "harness-secret-that-must-not-persist"
    adapter = HarnessEventCanonicalAdapter()
    catalog = default_event_schema_catalog()
    projector = EventSecurityProjector()
    events = (
        HarnessEvent(
            event_type=HarnessEventType.PHASE_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "phase": "verify",
                "boundary": "exit",
                "step_id": "collect",
                "input_refs": [],
                "output_refs": [],
                "gate_results": [
                    {
                        "gate": "quality",
                        "passed": False,
                        "details": {"answer": secret},
                    }
                ],
                "metadata": {"turn_count": 2},
                "occurred_at": "2026-07-15T08:00:00Z",
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.DECISION_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "decision_type": "retry_step",
                "run_id": "run-catalog",
                "step_id": "collect",
                "target_step_id": None,
                "reason": secret,
                "payload": {"worker_result": {"output": secret}},
                "decided_by": "harness",
                "decided_at": "2026-07-15T08:00:00Z",
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.WORKER_CALLED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "run_id": "run-catalog",
                "step_id": "collect",
                "worker_type": "llm",
                "inputs": {"prompt": secret},
                "metadata": {"model_hint": secret},
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.WORKER_RESULT_RECORDED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "status": "failed",
                "output": {"answer": secret},
                "artifacts": [],
                "diagnostics": {"provider": secret},
                "metrics": {"latency_ms": 1},
                "error": secret,
            },
            occurred_at=NOW,
        ),
        HarnessEvent(
            event_type=HarnessEventType.GATE_EVALUATED,
            run_id="run-catalog",
            step_id="collect",
            payload={
                "gate": "quality",
                "passed": False,
                "reason": secret,
                "details": {"answer": secret},
            },
            occurred_at=NOW,
        ),
    )

    serialized = []
    for event in events:
        request = adapter.to_publish_request(event)
        registration = catalog.get(request.event_type, request.data_schema)
        validated = catalog.validate(
            request.event_type,
            request.data_schema,
            request.payload or {},
        )
        projection = projector.project(
            payload=validated,
            payload_ref=request.payload_ref,
            extensions=request.extensions,
            policy=registration.sensitivity_policy,
            classification=request.security_classification,
            tenant_id=request.tenant_id,
        )
        serialized.append(stable_json_dumps(projection.payload))
        serialized.append(stable_json_dumps(projection.extensions))

    assert secret not in "".join(serialized)


def test_adapter_rejects_non_boolean_gate_result_without_type_coercion() -> None:
    with pytest.raises(HarnessValidationError, match="passed must be a boolean"):
        HarnessEventCanonicalAdapter().to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id="run-invalid-gate",
                step_id="collect",
                payload={
                    "phase": "verify",
                    "boundary": "exit",
                    "step_id": "collect",
                    "input_refs": [],
                    "output_refs": [],
                    "gate_results": [{"gate": "quality", "passed": "false"}],
                    "metadata": {},
                    "occurred_at": "2026-07-15T08:00:00Z",
                },
                occurred_at=NOW,
            )
        )


def test_commit_then_process_crash_keeps_store_authoritative_and_retry_is_idempotent() -> None:
    fail_once = True

    def fail_after(request: EventPublishRequest) -> bool:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            return True
        return False

    runtime = CanonicalRecordingRuntime(fail_after=fail_after)
    first_port = DurableHarnessEventPort(runtime)
    event = HarnessEvent(event_type=HarnessEventType.RUN_CREATED, run_id="run-crash", occurred_at=NOW)

    with pytest.raises(EventStoreUnavailableError, match="uncertain"):
        first_port.record(event)

    assert len(runtime.events) == 1
    assert first_port.events == []
    recovered_entry = event_log_entry_from_stored_event(runtime.events[0])
    assert recovered_entry.run_id == "run-crash"
    assert recovered_entry.stream_sequence == 1

    recovered_port = DurableHarnessEventPort(runtime)
    projected = recovered_port.record(event)
    assert projected.event_id == runtime.events[0].event_id
    assert len(runtime.events) == 1
    assert recovered_port.event_log_entries[0].stream_sequence == 1


def test_initialize_uncertain_retry_reuses_run_spec_identity() -> None:
    fail_once = True

    def fail_after(request: EventPublishRequest) -> bool:
        nonlocal fail_once
        if fail_once and request.event_type == HarnessEventType.RUN_CREATED:
            fail_once = False
            return True
        return False

    runtime = CanonicalRecordingRuntime(fail_after=fail_after)
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(event_port=port)
    run_spec = _run_spec("run-initialize-retry")

    with pytest.raises(EventStoreUnavailableError, match="uncertain"):
        control_plane.initialize(run_spec)
    recovered = control_plane.initialize(run_spec)

    assert recovered.status == HarnessRunStatus.CREATED
    assert len(runtime.events) == 1
    assert len(port.events) == 1
    assert runtime.events[0].occurred_at == run_spec.created_at


def test_phase_entry_commit_failure_prevents_gate_and_projection_progress() -> None:
    gate = CountingGate()
    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: (
            request.event_type == HarnessEventType.PHASE_RECORDED
            and request.payload is not None
            and request.payload.get("phase") == "plan"
            and request.payload.get("boundary") == "entry"
        )
    )
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        plan_gates=(gate,),
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    )

    with pytest.raises(EventStoreUnavailableError):
        control_plane.run(_run_spec("run-plan-failure"))

    assert gate.calls == 0
    assert all(
        not (
            event.event_type == HarnessEventType.PHASE_RECORDED
            and event.payload.get("boundary") == "entry"
            and event.payload.get("phase") == "plan"
        )
        for event in port.events
    )


def test_worker_is_not_called_until_worker_activity_event_commits() -> None:
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded")

    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: request.event_type == HarnessEventType.WORKER_CALLED
    )
    port = DurableHarnessEventPort(runtime)

    run_spec = _run_spec("run-worker-failure")
    control_plane = HarnessControlPlane(event_port=port, worker_registry={"collect": worker})
    with pytest.raises(EventStoreUnavailableError):
        control_plane.run(run_spec)

    assert worker_calls == 0
    assert all(event.event_type != HarnessEventType.WORKER_CALLED for event in port.events)


def test_terminal_commit_failure_never_returns_memory_only_success() -> None:
    runtime = CanonicalRecordingRuntime(
        fail_before=lambda request: (
            request.event_type == HarnessEventType.RUN_STATE_CHANGED
            and request.payload is not None
            and request.payload.get("status") == "succeeded"
        )
    )
    port = DurableHarnessEventPort(runtime)

    with pytest.raises(EventStoreUnavailableError):
        HarnessControlPlane(
            event_port=port,
            worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
        ).run(_run_spec("run-terminal-failure"))

    assert any(
        event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload.get("decision_type") == HarnessDecisionType.COMPLETE_RUN
        for event in port.events
    )
    assert all(
        not (
            event.event_type == HarnessEventType.RUN_STATE_CHANGED
            and event.payload.get("status") == "succeeded"
        )
        for event in port.events
    )


def test_plan_execute_verify_entry_and_exit_are_committed_in_order() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    ).run(_run_spec("run-phase-order"))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    boundaries = [
        (event.payload["phase"], event.payload["boundary"])
        for event in result.events
        if event.event_type == HarnessEventType.PHASE_RECORDED
    ]
    assert boundaries == [
        ("plan", "entry"),
        ("plan", "exit"),
        ("execute", "entry"),
        ("execute", "exit"),
        ("verify", "entry"),
        ("verify", "exit"),
    ]
    assert [event.stream_sequence for event in runtime.events] == list(
        range(1, len(runtime.events) + 1)
    )
    recovered_entries = tuple(event_log_entry_from_stored_event(event) for event in runtime.events)
    assert recovered_entries[-1].status_after == "succeeded"
    recovered = HarnessReplayReader().replay(
        run_id="run-phase-order",
        events=recovered_entries,
    )
    assert recovered.status == "succeeded"
    assert recovered.side_effects_replayed is False


def test_approval_resume_commits_before_continuation_and_does_not_repeat_worker() -> None:
    worker_calls = 0

    def worker(task) -> HarnessWorkerResult:
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(status="succeeded", output={"candidate": "ready"})

    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(event_port=port, worker_registry={"collect": worker})
    waiting = control_plane.run(_run_spec("run-approval", approval_required=True))
    assert waiting.state.status == HarnessRunStatus.WAITING_APPROVAL
    before_resume = len(runtime.events)

    resumed = control_plane.resume_after_approval(waiting.state, approved=True)

    assert resumed.state.status == HarnessRunStatus.SUCCEEDED
    assert worker_calls == 1
    resumed_events = runtime.events[before_resume:]
    assert resumed_events[0].event_type == HarnessEventType.DECISION_RECORDED
    assert resumed_events[0].payload["decision_type"] == HarnessDecisionType.RESUME_AFTER_APPROVAL
    assert resumed_events[1].event_type == HarnessEventType.RUN_STATE_CHANGED
    assert resumed_events[1].extensions["harness"]["metadata"]["transition_kind"] == "approval_resume"


def test_approval_cancel_is_durable_before_cancelled_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    )
    waiting = control_plane.run(_run_spec("run-cancel", approval_required=True))
    before_cancel = len(runtime.events)

    cancelled = control_plane.resume_after_approval(waiting.state, approved=False)

    assert cancelled.state.status == HarnessRunStatus.CANCELLED
    cancel_events = runtime.events[before_cancel:]
    assert cancel_events[0].event_type == HarnessEventType.DECISION_RECORDED
    assert cancel_events[0].payload["decision_type"] == HarnessDecisionType.CANCEL_RUN
    assert cancel_events[-1].event_type == HarnessEventType.RUN_STATE_CHANGED
    assert cancel_events[-1].payload["status"] == "cancelled"


def test_approval_resume_store_failure_leaves_input_state_unchanged() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    )
    waiting = control_plane.run(_run_spec("run-resume-failure", approval_required=True))
    state = waiting.state
    runtime.fail_before = lambda request: (
        request.event_type == HarnessEventType.DECISION_RECORDED
        and request.payload is not None
        and request.payload.get("decision_type") == HarnessDecisionType.RESUME_AFTER_APPROVAL
    )

    with pytest.raises(EventStoreUnavailableError):
        control_plane.resume_after_approval(state, approved=True)

    assert state.status == HarnessRunStatus.WAITING_APPROVAL
    assert not any(
        event.event_type == HarnessEventType.RUN_STATE_CHANGED
        and event.metadata.get("transition_kind") == "approval_resume"
        for event in port.events
    )


def test_approval_resume_without_resolved_activity_fails_before_durable_progress() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    control_plane = HarnessControlPlane(
        event_port=port,
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    )
    waiting = control_plane.run(_run_spec("run-resume-preflight", approval_required=True))
    step_id = waiting.state.current_step_id
    assert step_id is not None
    unresolved_steps = tuple(
        replace(step, metadata={"worker_result_ref": "sha256:" + "1" * 64})
        if step.step_id == step_id
        else step
        for step in waiting.state.step_states
    )
    unresolved = replace(waiting.state, step_states=unresolved_steps)
    before = len(runtime.events)

    with pytest.raises(HarnessValidationError, match="committed worker result"):
        control_plane.resume_after_approval(unresolved, approved=True)

    assert len(runtime.events) == before
    assert unresolved.status == HarnessRunStatus.WAITING_APPROVAL


def test_adapter_rejects_conflicting_duplicate_business_context() -> None:
    adapter = HarnessEventCanonicalAdapter()
    event = HarnessEvent(
        event_type=HarnessEventType.DECISION_RECORDED,
        run_id="run-authority",
        payload={
            "decision_type": "complete_run",
            "run_id": "another-run",
            "payload": {},
            "decided_by": "harness",
            "decided_at": "2026-07-15T08:00:00Z",
        },
        occurred_at=NOW,
    )

    with pytest.raises(HarnessValidationError, match="run_id conflicts"):
        adapter.to_publish_request(event)


def test_adapter_rejects_conflicting_duplicate_time_and_none_step_text() -> None:
    adapter = HarnessEventCanonicalAdapter()
    with pytest.raises(HarnessValidationError, match="occurred_at conflicts"):
        adapter.to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id="run-time-authority",
                step_id="collect",
                payload={
                    "phase": "plan",
                    "boundary": "entry",
                    "step_id": "collect",
                    "input_refs": [],
                    "output_refs": [],
                    "gate_results": [],
                    "metadata": {},
                    "occurred_at": "1999-01-01T00:00:00Z",
                },
                occurred_at=NOW,
            )
        )

    with pytest.raises(HarnessValidationError, match="step_id conflicts"):
        adapter.to_publish_request(
            HarnessEvent(
                event_type=HarnessEventType.RUN_STATE_CHANGED,
                run_id="run-step-authority",
                payload={"status": "running", "step_id": "None"},
                occurred_at=NOW,
            )
        )


def test_adapter_rejects_unbounded_legacy_trace_value_before_runtime() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)

    with pytest.raises(HarnessValidationError, match="trace_id has an unsafe format"):
        port.record(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id="run-trace-secret",
                trace_id="sk-trace-secret",
                occurred_at=NOW,
            )
        )

    assert runtime.attempts == []
    assert runtime.events == []


@pytest.mark.parametrize(
    "run_id",
    (
        "..",
        "../escape",
        "/absolute",
        r"C:\absolute",
        r"C:drive-relative",
        r"\\server\share",
        r"\\?\C:\device",
        "run:alternate-stream",
        "CON",
        "LPT1.txt",
    ),
)
def test_unsafe_run_id_fails_before_runtime_or_stream_derivation(run_id: str) -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)

    with pytest.raises(ValueError):
        port.record(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_id,
                occurred_at=NOW,
            )
        )

    assert runtime.attempts == []
    assert runtime.events == []
    assert port.events == []


def test_retry_and_terminal_failure_decisions_precede_state_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    workflow = HarnessWorkflowSpec(
        workflow_id="retry-order",
        steps=(
            HarnessStepSpec(
                step_id="collect",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(max_attempts=2, retry_on_statuses=("failed",)),
            ),
        ),
        entry_step_id="collect",
    )
    result = HarnessControlPlane(
        event_port=port,
        worker_registry={
            "collect": (
                HarnessWorkerResult(status="failed", error="first"),
                HarnessWorkerResult(status="failed", error="second"),
            )
        },
    ).run(HarnessRunSpec(run_id="run-retry-order", workflow=workflow))

    assert result.state.status == HarnessRunStatus.FAILED
    retry_decision = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload["decision_type"] == HarnessDecisionType.RETRY_STEP,
    )
    retry_projection = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.STEP_STATE_CHANGED
        and event.extensions["harness"]["metadata"].get("transition_kind") == "retry",
    )
    failure_decision = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload["decision_type"] == HarnessDecisionType.FAIL_RUN,
    )
    failure_projection = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.RUN_STATE_CHANGED
        and event.payload["status"] == "failed",
    )
    assert retry_decision < retry_projection
    assert failure_decision < failure_projection


def test_route_to_repair_and_budget_halt_have_durable_transition_kinds() -> None:
    repair_runtime = CanonicalRecordingRuntime()
    repair_port = DurableHarnessEventPort(repair_runtime)
    repair_workflow = HarnessWorkflowSpec(
        workflow_id="repair-order",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(repair_step_id="repair"),
                metadata={"output_schema": {"required": ["title"]}},
            ),
            HarnessStepSpec(step_id="repair", worker_type="llm"),
        ),
        entry_step_id="draft",
    )
    HarnessControlPlane(
        event_port=repair_port,
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(status="succeeded", output={"body": "missing"}),
            "repair": lambda task: HarnessWorkerResult(status="succeeded", output={"title": "fixed"}),
        },
    ).run(HarnessRunSpec(run_id="run-repair-order", workflow=repair_workflow))
    repair_decision = _event_index(
        repair_runtime.events,
        lambda event: event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload["decision_type"] == HarnessDecisionType.ROUTE_TO_REPAIR,
    )
    repair_projection = _event_index(
        repair_runtime.events,
        lambda event: event.event_type == HarnessEventType.STEP_STATE_CHANGED
        and event.extensions["harness"]["metadata"].get("transition_kind") == "route_to_repair",
    )
    assert repair_decision < repair_projection

    halt_runtime = CanonicalRecordingRuntime()
    halt_port = DurableHarnessEventPort(halt_runtime)
    halted = HarnessControlPlane(
        event_port=halt_port,
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded")},
    ).run(
        HarnessRunSpec(
            run_id="run-budget-halt",
            workflow=_run_spec("ignored").workflow,
            budget=HarnessBudget(
                max_turns=2,
                max_replans=0,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )
    assert halted.state.status == HarnessRunStatus.HALTED
    budget_decision = _event_index(
        halt_runtime.events,
        lambda event: event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload["decision_type"] == HarnessDecisionType.HALT_RUN,
    )
    budget_projection = _event_index(
        halt_runtime.events,
        lambda event: event.event_type == HarnessEventType.RUN_STATE_CHANGED
        and event.extensions["harness"]["metadata"].get("transition_kind") == "budget_exhaustion",
    )
    assert budget_decision < budget_projection


def test_replan_decision_commits_before_replanning_projection() -> None:
    runtime = CanonicalRecordingRuntime()
    port = DurableHarnessEventPort(runtime)
    workflow = HarnessWorkflowSpec(
        workflow_id="replan-order",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                metadata={"output_schema": {"required": ["title"]}},
            ),
        ),
        entry_step_id="draft",
    )
    HarnessControlPlane(
        event_port=port,
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(status="succeeded", output={"body": "missing"})
        },
    ).run(
        HarnessRunSpec(
            run_id="run-replan-order",
            workflow=workflow,
            budget=HarnessBudget(
                max_turns=20,
                max_replans=1,
                max_retries_per_step=0,
                max_worker_calls=10,
            ),
        )
    )

    decision_index = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.DECISION_RECORDED
        and event.payload["decision_type"] == HarnessDecisionType.REPLAN_STEP,
    )
    state_index = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.RUN_STATE_CHANGED
        and event.extensions["harness"]["metadata"].get("transition_kind") == "replan",
    )
    entry_index = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.PHASE_RECORDED
        and event.payload.get("phase") == "replan"
        and event.payload.get("boundary") == "entry",
    )
    exit_index = _event_index(
        runtime.events,
        lambda event: event.event_type == HarnessEventType.PHASE_RECORDED
        and event.payload.get("phase") == "replan"
        and event.payload.get("boundary") == "exit",
    )
    assert decision_index < entry_index < state_index < exit_index


def _run_spec(run_id: str, *, approval_required: bool = False) -> HarnessRunSpec:
    return HarnessRunSpec(
        run_id=run_id,
        workflow=HarnessWorkflowSpec(
            workflow_id="durable-boundary",
            steps=(
                HarnessStepSpec(
                    step_id="collect",
                    worker_type="llm",
                    metadata={"approval_required": approval_required},
                ),
            ),
            entry_step_id="collect",
        ),
    )


def _event_index(
    events: list[StoredEvent],
    predicate: Callable[[StoredEvent], bool],
) -> int:
    return next(index for index, event in enumerate(events) if predicate(event))
