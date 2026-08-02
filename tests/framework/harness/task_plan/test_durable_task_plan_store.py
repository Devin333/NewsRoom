from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock

import pytest

from framework.agent.artifacts.models import ArtifactRef, ArtifactWriteRequest
from framework.events.canonical import EventCandidate, StoredEvent
from framework.events.errors import EventStreamVersionConflictError
from framework.events.runtime.models import (
    AppendResult,
    EventPage,
    StreamReadRequest,
)
from framework.events.runtime.publisher import EventPublishRequest, EventRuntime
from framework.events.schema import default_event_schema_catalog
from framework.harness.task_plan import (
    DurableTaskPlanStore,
    PlanBuildBudget,
    PlanCandidate,
    PlanPatch,
    PlanPatchOperation,
    PlanPatchOperationType,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
    TaskLifecycle,
    TaskOutputContract,
    TaskPlanEvent,
    TaskPlanReadyDecision,
    TaskPlanScheduler,
    TaskPlanValidationContext,
    TaskPlanValidator,
    TaskResultRecord,
    TaskRetryPolicy,
    TaskSpec,
    ValidatedTaskPlan,
    task_instance_for_attempt,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.patches import TaskPlanPatchValidator
from framework.harness.task_plan.policy import TaskPlanPolicy
from framework.harness.workflow.binding_authority import HarnessWorkerBinding
from framework.harness.workflow.graph import HarnessContractKind, HarnessContractReference
from framework.harness.workflow.step import HarnessWorkerType


FIXED_NOW = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)


class _Worker:
    worker_type = HarnessWorkerType.LLM

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id
        self.worker_version = "1"

    def execute(self, task):
        return {"status": "succeeded", "task_id": task.get("task_id")}


class _ArtifactStore:
    """Small immutable artifact adapter used to exercise the durable boundary."""

    def __init__(self) -> None:
        self._content: dict[tuple[str, str], bytes] = {}

    def write(self, artifact: ArtifactWriteRequest) -> ArtifactRef:
        content = artifact.content_bytes()
        if artifact.relative_path is None or artifact.artifact_id is None:
            raise AssertionError("TaskPlan adapter must pin artifact identity and path")
        key = (artifact.run_id, artifact.relative_path)
        previous = self._content.get(key)
        if previous is not None and previous != content:
            raise AssertionError("immutable artifact identity was reused")
        self._content[key] = content
        return ArtifactRef(
            artifact_id=artifact.artifact_id,
            run_id=artifact.run_id,
            artifact_type=artifact.artifact_type,
            path=artifact.relative_path,
            content_type=artifact.content_type,
            size_bytes=len(content),
            checksum=_sha256(content),
            redacted=artifact.redacted,
            metadata=dict(artifact.metadata),
        )

    def read(self, artifact_ref: ArtifactRef) -> bytes:
        try:
            content = self._content[(artifact_ref.run_id, artifact_ref.path)]
        except KeyError as exc:
            raise FileNotFoundError(artifact_ref.path) from exc
        if artifact_ref.checksum is not None and _sha256(content) != artifact_ref.checksum:
            raise ValueError("artifact checksum mismatch")
        if artifact_ref.size_bytes is not None and len(content) != artifact_ref.size_bytes:
            raise ValueError("artifact size mismatch")
        return content

    def exists(self, artifact_ref: ArtifactRef) -> bool:
        return (artifact_ref.run_id, artifact_ref.path) in self._content


def _sha256(content: bytes) -> str:
    from hashlib import sha256

    return sha256(content).hexdigest()


class _UnitOfWork:
    def __init__(self, store: "_EventStore") -> None:
        self.store = store
        self.pending: list[StoredEvent] = []
        self.finished = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if not self.finished:
            self.rollback()
        return False

    def append_event(
        self,
        event: EventCandidate,
        *,
        expected_last_sequence: int | None = None,
    ) -> AppendResult:
        stream_events = self.store._stream_events(event.stream_id, event.tenant_id)
        current = (stream_events[-1].stream_sequence if stream_events else 0) + len(self.pending)
        if expected_last_sequence is not None and expected_last_sequence != current:
            raise EventStreamVersionConflictError(
                stream_id=event.stream_id,
                expected_last_sequence=expected_last_sequence,
                actual_last_sequence=current,
            )
        for existing in (*stream_events, *self.pending):
            if existing.event_id == event.event_id:
                if existing.content_checksum != event.content_checksum:
                    raise ValueError("event identity collision")
                return AppendResult(event=existing, created=False, pending_delivery_count=0)
        stored = StoredEvent(
            candidate=event,
            observed_at=FIXED_NOW,
            stream_sequence=current + 1,
        )
        self.pending.append(stored)
        return AppendResult(event=stored, created=True, pending_delivery_count=0)

    def commit(self) -> None:
        if self.finished:
            raise RuntimeError("unit of work already finished")
        with self.store._lock:
            self.store._events.extend(self.pending)
        self.finished = True

    def rollback(self) -> None:
        self.pending.clear()
        self.finished = True


class _EventStore:
    """In-process canonical event store with the production stream contract."""

    def __init__(self, *, fail_on_event_type: str | None = None) -> None:
        self._events: list[StoredEvent] = []
        self._lock = Lock()
        self.fail_on_event_type = fail_on_event_type

    def unit_of_work(self) -> _UnitOfWork:
        return _FailingUnitOfWork(self) if self.fail_on_event_type else _UnitOfWork(self)

    def get_event(self, event_id: str, *, tenant_id: str | None = None) -> StoredEvent | None:
        with self._lock:
            return next(
                (item for item in self._events if item.event_id == event_id and item.tenant_id == tenant_id),
                None,
            )

    def get_stream_high_watermark(self, stream_id: str, *, tenant_id: str | None = None) -> int | None:
        with self._lock:
            events = self._stream_events(stream_id, tenant_id)
            return events[-1].stream_sequence if events else None

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        with self._lock:
            events = list(self._stream_events(request.stream_id, request.tenant_id))
        high = events[-1].stream_sequence if events else None
        if high is None:
            return EventPage(request.stream_id, (), None, tenant_id=request.tenant_id)
        start = request.cursor.after_sequence if request.cursor is not None else 0
        through = request.through_sequence or high
        selected = [
            item
            for item in events
            if start < item.stream_sequence <= through
            and (not request.event_types or item.event_type in request.event_types)
            and (not request.data_schemas or item.data_schema in request.data_schemas)
        ][: request.limit]
        next_cursor = None
        if selected and selected[-1].stream_sequence < through:
            from framework.events.runtime.models import StreamSequenceCursor

            next_cursor = StreamSequenceCursor(
                request.stream_id,
                selected[-1].stream_sequence,
                through,
                request.tenant_id,
            )
        return EventPage(
            request.stream_id,
            tuple(selected),
            high,
            next_cursor,
            request.tenant_id,
        )

    def _stream_events(self, stream_id: str, tenant_id: str | None) -> list[StoredEvent]:
        return [
            item
            for item in self._events
            if item.stream_id == stream_id and item.tenant_id == tenant_id
        ]


class _FailingUnitOfWork(_UnitOfWork):
    def append_event(self, event: EventCandidate, *, expected_last_sequence: int | None = None) -> AppendResult:
        if event.event_type == self.store.fail_on_event_type:
            raise RuntimeError("injected batch failure")
        return super().append_event(event, expected_last_sequence=expected_last_sequence)


class _ConflictOnceRuntime:
    def __init__(self, delegate: EventRuntime) -> None:
        self.delegate = delegate
        self.conflicts = 0

    def publish(self, event: EventPublishRequest, *, expected_last_sequence=None, unit_of_work=None):
        if self.conflicts == 0:
            self.conflicts += 1
            raise EventStreamVersionConflictError(
                stream_id=event.stream_id,
                expected_last_sequence=int(expected_last_sequence or 0),
                actual_last_sequence=int(expected_last_sequence or 0) + 1,
            )
        return self.delegate.publish(event, expected_last_sequence=expected_last_sequence, unit_of_work=unit_of_work)

    def publish_batch(self, events: Sequence[EventPublishRequest], *, expected_last_sequence=None):
        return self.delegate.publish_batch(events, expected_last_sequence=expected_last_sequence)


def _runtime(store: _EventStore) -> EventRuntime:
    return EventRuntime(store=store, schema_catalog=default_event_schema_catalog(), monotonic=lambda: 1.0)


def _policy_and_registry(*, two_tasks: bool = False):
    capabilities = ("research.structure", "research.helper") if two_tasks else ("research.structure",)
    roles = ("analysis.structure", "analysis.helper") if two_tasks else ("analysis.structure",)
    workers = [_Worker(f"{capability}-worker") for capability in capabilities]
    registrations = tuple(
        TaskCapabilityRegistration(
            capability=capability,
            worker_binding=HarnessWorkerBinding(
                HarnessContractReference(HarnessContractKind.WORKER, worker.worker_id, "1"),
                HarnessWorkerType.LLM,
                worker,
            ),
            worker_contract_ref=f"{capability}-contract@1",
            input_schema_ref="schema://input@1",
            output_schema_ref=f"schema://{roles[index]}@1",
        )
        for index, (capability, worker) in enumerate(zip(capabilities, workers, strict=True))
    )
    policy = TaskPlanPolicy(
        policy_id="research.analysis",
        version="1",
        stage_id="dynamic_analysis_stage",
        allowed_worker_capabilities=capabilities,
        allowed_subagent_ids=(),
        allowed_tool_ids=(),
        allowed_memory_namespaces=(),
        allowed_input_refs=("document",),
        allowed_output_roles=roles,
        required_output_roles=("analysis.structure",),
        allowed_output_schema_refs=tuple(f"schema://{role}@1" for role in roles),
        allowed_gate_refs=("SummaryGate@1",),
        deterministic_aggregator_refs={},
        pinned_capability_bindings={capability: f"{capability}-worker@1" for capability in capabilities},
        required_worker_contract_refs={capability: f"{capability}-contract@1" for capability in capabilities},
        max_tasks=8,
        max_depth=4,
        max_parallelism=2,
        max_replans=2,
        max_task_attempts=2,
        max_plan_build_calls=1,
        max_plan_build_turns=1,
        max_plan_build_tool_calls=0,
        per_task_budget=TaskBudget(max_turns=1),
        aggregate_task_budget=TaskBudget(max_turns=8),
    )
    return policy, TaskCapabilityRegistry(registrations)


def _task(task_id: str, *, capability: str = "research.structure", role: str = "analysis.structure") -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        objective=f"Analyze {task_id}",
        worker_capability=capability,
        input_refs=("document",),
        output_contract=TaskOutputContract(f"schema://{role}@1", role),
        acceptance_criteria=TaskAcceptanceCriteria(("SummaryGate@1",)),
        budget_request=TaskBudget(max_turns=1),
        retry_policy=TaskRetryPolicy(max_attempts=1),
    )


def _candidate(tasks: tuple[TaskSpec, ...], *, two_tasks: bool = False) -> PlanCandidate:
    graph_checksum = canonical_payload_checksum({"graph": "durable-task-plan"})
    return PlanCandidate(
        candidate_id="candidate-1" if not two_tasks else "candidate-2",
        run_id="durable-run",
        workflow_id="research.dynamic",
        stage_id="dynamic_analysis_stage",
        graph_checksum=graph_checksum,
        input_context_refs=("document",),
        tasks=tasks,
        required_output_roles=("analysis.structure",),
        generated_by="planner@1",
        requested_plan_budget=PlanBuildBudget(),
    )


def _accepted_plan(tasks: tuple[TaskSpec, ...], *, two_tasks: bool = False):
    policy, registry = _policy_and_registry(two_tasks=two_tasks)
    candidate = _candidate(tasks, two_tasks=two_tasks)
    context = TaskPlanValidationContext(
        run_id=candidate.run_id,
        workflow_id=candidate.workflow_id,
        stage_id=candidate.stage_id,
        graph_checksum=candidate.graph_checksum,
        available_input_refs=("document",),
        registered_gate_refs=policy.allowed_gate_refs,
        dynamic_stage_declared=True,
    )
    plan = TaskPlanValidator().accept(candidate, policy, registry, context=context, accepted_at="2026-08-02T00:00:00Z")
    return candidate, plan, policy, registry


def _store(event_store: _EventStore, artifacts: _ArtifactStore, *, runtime=None) -> DurableTaskPlanStore:
    return DurableTaskPlanStore(
        runtime or _runtime(event_store),
        event_store,
        artifact_store=artifacts,
        clock=lambda: FIXED_NOW,
    )


def _lifecycle_event(event_type: str, sequence: int, plan: ValidatedTaskPlan, instance) -> TaskPlanEvent:
    return TaskPlanEvent(
        event_type,
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        task_id=instance.task_id,
        task_instance_id=instance.task_instance_id,
        attempt=instance.attempt,
        input_checksum=instance.task_definition_checksum,
        sequence=sequence,
    )


def _start(store: DurableTaskPlanStore, plan: ValidatedTaskPlan, task_id: str):
    scheduler = TaskPlanScheduler()
    instance = task_instance_for_attempt(plan, task_id, 1)
    projection = store.load_projection(plan.run_id, plan.stage_id)
    decision = TaskPlanReadyDecision((instance,))
    projection = scheduler.reserve_ready_tasks(projection, decision)
    first_sequence = len(store.read_events(plan.run_id, plan.stage_id)) + 1
    for sequence, event_type, transition in (
        (first_sequence, "TASK_READY", lambda value: value),
        (first_sequence + 1, "TASK_DISPATCHED", lambda value: scheduler.mark_dispatched(value, instance)),
        (first_sequence + 2, "TASK_STARTED", lambda value: scheduler.mark_started(value, instance)),
    ):
        projection = replace(transition(projection), last_sequence=sequence)
        store.commit_event(_lifecycle_event(event_type, sequence, plan, instance), projection)
    return instance


def _result(plan: ValidatedTaskPlan, instance, *, status: TaskLifecycle, role: str = "analysis.structure") -> TaskResultRecord:
    definition = next(item for item in plan.tasks if item.task_id == instance.task_id)
    if status is TaskLifecycle.SUCCEEDED:
        return TaskResultRecord(
            run_id=plan.run_id,
            workflow_id=plan.workflow_id,
            stage_id=plan.stage_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            task_id=instance.task_id,
            task_instance_id=instance.task_instance_id,
            attempt=instance.attempt,
            worker_ref=instance.worker_ref,
            task_checksum=instance.task_definition_checksum,
            binding_checksum=definition.binding_checksum,
            status=status,
            result_ref=f"result://{instance.task_id}",
            output_refs=(f"artifact://{instance.task_id}",),
            output_roles=(role,),
            output_schema_ref=f"schema://{role}@1",
        )
    return TaskResultRecord(
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        task_id=instance.task_id,
        task_instance_id=instance.task_instance_id,
        attempt=instance.attempt,
        worker_ref=instance.worker_ref,
        task_checksum=instance.task_definition_checksum,
        binding_checksum=definition.binding_checksum,
        status=status,
        error_code="worker_failed",
    )


def test_durable_store_rebuilds_plan_projection_and_artifacts_after_reopen():
    artifacts = _ArtifactStore()
    event_store = _EventStore()
    store = _store(event_store, artifacts)
    candidate, plan, _, _ = _accepted_plan((_task("structure"),))

    assert store.append_candidate(candidate) == candidate.candidate_checksum
    assert store.accept_plan(plan) == plan.plan_checksum
    reopened = _store(event_store, artifacts)

    assert reopened.plan(plan.run_id, plan.stage_id) == plan
    assert reopened.plan(plan.run_id, plan.stage_id, 1) == plan
    projection = reopened.load_projection(plan.run_id, plan.stage_id)
    assert projection.plan_checksum == plan.plan_checksum
    assert projection.last_sequence == 2
    assert [event.event_type for event in reopened.read_events(plan.run_id, plan.stage_id)] == [
        "PLAN_CANDIDATE_BUILT",
        "PLAN_ACCEPTED",
    ]


def test_rejected_candidate_batch_is_atomic_when_second_event_fails():
    artifacts = _ArtifactStore()
    event_store = _EventStore(fail_on_event_type="PLAN_VALIDATION_FAILED")
    store = _store(event_store, artifacts)
    candidate, _, _, _ = _accepted_plan((_task("structure"),))

    with pytest.raises(RuntimeError, match="injected batch failure"):
        store.append_rejected_candidate(candidate, reason_code="invalid_candidate")

    assert event_store.get_stream_high_watermark("run:durable-run") is None
    assert store.read_events(candidate.run_id, candidate.stage_id) == ()


def test_durable_store_retries_a_concurrent_sequence_conflict_without_duplicate_event():
    artifacts = _ArtifactStore()
    event_store = _EventStore()
    delegate = _runtime(event_store)
    runtime = _ConflictOnceRuntime(delegate)
    store = _store(event_store, artifacts, runtime=runtime)
    candidate, _, _, _ = _accepted_plan((_task("structure"),))

    store.append_candidate(candidate)

    assert runtime.conflicts == 1
    events = store.read_events(candidate.run_id, candidate.stage_id)
    assert len(events) == 1
    assert events[0].event_type == "PLAN_CANDIDATE_BUILT"
    assert event_store.get_stream_high_watermark("run:durable-run") == 1


def test_patch_and_terminal_result_are_recoverable_from_event_and_artifact_refs():
    artifacts = _ArtifactStore()
    event_store = _EventStore()
    store = _store(event_store, artifacts)
    candidate, plan, policy, registry = _accepted_plan(
        (_task("structure"), _task("helper", capability="research.helper", role="analysis.helper")),
        two_tasks=True,
    )
    store.append_candidate(candidate)
    store.accept_plan(plan)

    structure_instance = _start(store, plan, "structure")
    structure_result = _result(plan, structure_instance, status=TaskLifecycle.SUCCEEDED)
    store.append_result(structure_result)
    helper_instance = _start(store, plan, "helper")
    helper_failure = _result(plan, helper_instance, status=TaskLifecycle.FAILED)
    store.append_result(helper_failure)

    patch = PlanPatch(
        patch_id="patch-1",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="replacement",
        source_candidate_ref="candidate://replacement",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.ADD_REPLACEMENT_TASK,
                target_task_id="helper",
                replacement_task=_task(
                    "helper-replacement",
                    capability="research.helper",
                    role="analysis.helper",
                ),
            ),
        ),
    )
    next_plan = TaskPlanPatchValidator().apply(
        plan,
        patch,
        store.load_projection(plan.run_id, plan.stage_id),
        policy,
        registry,
        accepted_at="2026-08-02T00:01:00Z",
        available_input_refs=("document",),
    )
    store.accept_patched_plan(patch, next_plan)

    reopened = _store(event_store, artifacts)
    assert reopened.plan(plan.run_id, plan.stage_id, 1) == plan
    assert reopened.plan(plan.run_id, plan.stage_id, 2) == next_plan
    recovered = reopened.load_projection(plan.run_id, plan.stage_id)
    assert next(item for item in recovered.tasks if item.task_id == "structure").status is TaskLifecycle.SUCCEEDED
    assert next(item for item in recovered.tasks if item.task_id == "helper").status is TaskLifecycle.FAILED
    assert next(item for item in recovered.tasks if item.task_id == "helper-replacement").status is TaskLifecycle.PENDING
    assert reopened.results_for(plan.run_id, plan.stage_id, next_plan.plan_id, 2) == (structure_result,)
    event_types = [event.event_type for event in reopened.read_events(plan.run_id, plan.stage_id)]
    assert "PLAN_PATCH_ACCEPTED" in event_types
    assert event_types[-2:] == ["PLAN_PATCH_ACCEPTED", "PLAN_ACCEPTED"]
