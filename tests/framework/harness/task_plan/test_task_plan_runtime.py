from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan import (
    FakePlanCandidateBuilder,
    InMemoryTaskPlanStore,
    PlanBuildBudget,
    PlanCandidate,
    PlanPatch,
    PlanPatchOperation,
    PlanPatchOperationType,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
    TaskOutputContract,
    TaskPlanEvent,
    TaskPlanPolicy,
    TaskPlanScheduler,
    TaskPlanStageRequest,
    TaskPlanStageIdentity,
    TaskPlanStageRunner,
    TaskPlanValidator,
    TaskResultRecord,
    TaskSpec,
    TaskLifecycle,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.inspection import (
    TaskPlanInspectionDecision,
    TaskPlanInspectionRequest,
    TaskPlanInspectionService,
    TaskPlanReplayVerdict,
)
from framework.harness.task_plan.observability import (
    TaskPlanMetricSample,
    task_plan_metric_samples,
    task_plan_trace_events,
)
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.workers.result import HarnessWorkerResult
from tests.fixtures.task_plan import build_task_plan_stage_binding


class _Worker:
    worker_id = "worker"
    worker_version = "1"
    worker_type = HarnessWorkerType.LLM

    def execute(self, task):
        return HarnessWorkerResult(status="succeeded", output={"value": task["task_id"] if "task_id" in task else "ok"})


class _AcceptingResultVerifier:
    def verify(self, result, *, task, request):
        instance = request.instance
        return TaskResultRecord.for_plan(
            request.plan,
            task_id=instance.task_id,
            task_instance_id=instance.task_instance_id,
            attempt=instance.attempt,
            status=TaskLifecycle.SUCCEEDED,
            result_ref=f"result://{instance.task_id}",
            output_roles=(task.output_role,),
            output_schema_ref=task.task.output_contract.schema_ref,
            verified_gate_refs=task.gate_refs,
            gate_evidence_refs=tuple(
                f"evidence://gate/{index}"
                for index, _gate_ref in enumerate(task.gate_refs, start=1)
            ),
        )


def _setup(*, roles=("role",), capabilities=("cap",)):
    policy = TaskPlanPolicy(
        policy_id="test.task-plan",
        version="1",
        stage_id="dynamic_stage",
        allowed_worker_capabilities=capabilities,
        allowed_subagent_ids=(),
        allowed_tool_ids=(),
        allowed_memory_namespaces=(),
        allowed_input_refs=("document",),
        allowed_output_roles=roles,
        required_output_roles=roles,
        allowed_output_schema_refs=("schema://result@1",),
        allowed_gate_refs=("gate@1",),
        deterministic_aggregator_refs={},
        pinned_capability_bindings={capability: f"{capability}-worker@1" for capability in capabilities},
        required_worker_contract_refs={capability: f"{capability}-contract@1" for capability in capabilities},
        max_tasks=8,
        max_depth=8,
        max_parallelism=2,
        max_replans=1,
        max_task_attempts=2,
        max_plan_build_calls=1,
        max_plan_build_turns=2,
        max_plan_build_tool_calls=0,
        per_task_budget=TaskBudget(max_turns=2),
        aggregate_task_budget=TaskBudget(max_turns=8),
    )
    stage_binding = build_task_plan_stage_binding(
        graph_id="graph",
        stage_id=policy.stage_id,
        policy_ref=policy.exact_ref,
        required_output_roles=policy.required_output_roles,
    )
    registrations = []
    for capability in capabilities:
        worker = _Worker()
        worker.worker_id = f"{capability}-worker"
        binding = HarnessWorkerBinding(
            HarnessContractReference(HarnessContractKind.WORKER, worker.worker_id, "1"),
            HarnessWorkerType.LLM,
            worker,
        )
        registrations.append(TaskCapabilityRegistration(
            capability,
            binding,
            f"{capability}-contract@1",
            "schema://input@1",
            "schema://result@1",
        ))
    return stage_binding, policy, TaskCapabilityRegistry(registrations)


def _task(task_id: str, capability: str = "cap", role: str = "role", depends_on=()):
    return TaskSpec(
        task_id=task_id,
        objective=f"objective-{task_id}",
        worker_capability=capability,
        input_refs=("document",),
        output_contract=TaskOutputContract("schema://result@1", role),
        acceptance_criteria=TaskAcceptanceCriteria(("gate@1",)),
        depends_on=depends_on,
        budget_request=TaskBudget(max_turns=1),
        retry_policy={"max_attempts": 1, "retryable_reason_codes": []},
    )


def _candidate(stage_binding, tasks, roles=("role",)):
    return PlanCandidate.for_stage(
        stage_identity=TaskPlanStageIdentity("run", stage_binding),
        candidate_id="candidate",
        input_context_refs=("document",),
        tasks=tuple(tasks),
        required_output_roles=roles,
        generated_by="planner@1",
        requested_plan_budget=PlanBuildBudget(),
    )


def test_validation_rejects_cycle_without_binding_or_worker_activity():
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a", depends_on=("b",)), _task("b", depends_on=("a",))))
    result = TaskPlanValidator().validate(
        candidate,
        policy=policy,
        capabilities=registry,
        context=validator_context(graph),
    )
    assert not result.accepted
    assert "dependency_cycle" in {item.code for item in result.diagnostics}


def test_scheduler_orders_ready_tasks_and_honors_parallelism():
    graph, policy, registry = _setup(roles=("role_a", "role_b"))
    candidate = _candidate(graph, (_task("b", role="role_b"), _task("a", role="role_a")), roles=("role_a", "role_b"))
    validator = TaskPlanValidator()
    context = validator_context(graph)
    plan = validator.accept(
        candidate,
        policy,
        registry,
        context=context,
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    decision = TaskPlanScheduler().next_ready_tasks(
        store.load_projection("run", "dynamic_stage"),
        1,
        plan=plan,
        policy=policy,
        available_input_refs=("document",),
    )
    assert [item.task_id for item in decision.task_instances] == ["a"]


def test_ready_task_is_durably_committed_before_worker_invocation() -> None:
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a"),))
    store = InMemoryTaskPlanStore()
    event_types_at_worker_call: list[str] = []

    def execute(_binding, _request):
        event_types_at_worker_call.extend(
            event.event_type
            for event in store.read_events("run", "dynamic_stage")
        )
        return HarnessWorkerResult(status="succeeded", output={"value": "accepted"})

    result = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(candidate),
        capability_registry=registry,
        store=store,
        result_verifier=_AcceptingResultVerifier(),
        worker_executor=execute,
    ).run(
        TaskPlanStageRequest(
            run_id="run",
            stage_binding=graph,
            context_refs={"document": "document"},
            policy=policy,
            policy_ref=policy.exact_ref,
            candidate=candidate,
            accepted_at="2026-08-01T00:00:00Z",
        )
    )

    assert result.status.value == "succeeded"
    assert event_types_at_worker_call[-3:] == [
        "TASK_READY",
        "TASK_DISPATCHED",
        "TASK_STARTED",
    ]


def test_store_accepts_duplicate_identical_result_once():
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a"),))
    validator = TaskPlanValidator()
    plan = validator.accept(
        candidate,
        policy,
        registry,
        context=validator_context(graph),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    scheduler = TaskPlanScheduler()
    decision = scheduler.next_ready_tasks(store.load_projection("run", "dynamic_stage"), 1, plan=plan, policy=policy, available_input_refs=("document",))
    store.update_projection(scheduler.mark_dispatched(scheduler.reserve_ready_tasks(store.load_projection("run", "dynamic_stage"), decision), decision.task_instances[0]))
    instance = decision.task_instances[0]
    result = TaskResultRecord.for_plan(
        plan,
        task_id="a",
        task_instance_id=instance.task_instance_id,
        attempt=1,
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://a",
        output_refs=("artifact://a",),
        output_roles=("role",),
        output_schema_ref="schema://result@1",
    )
    assert store.append_result(result) == store.append_result(result)
    assert len(store.results_for("run", "dynamic_stage", plan.plan_id, 1)) == 1


def validator_context(stage_binding):
    from framework.harness.task_plan import TaskPlanValidationContext

    return TaskPlanValidationContext(
        run_id="run",
        stage_binding=stage_binding,
        available_input_refs=("document",),
        registered_gate_refs=("gate@1",),
    )


class _InspectionAuthorizer:
    def __init__(self, authorized: bool) -> None:
        self.authorized = authorized
        self.calls = 0

    def authorize(self, request: TaskPlanInspectionRequest) -> TaskPlanInspectionDecision:
        self.calls += 1
        if self.authorized:
            return TaskPlanInspectionDecision(True, "authz://task-plan/read")
        return TaskPlanInspectionDecision(False, denial_reason_code="tenant_scope_denied")


class _CountingStore(InMemoryTaskPlanStore):
    def __init__(self) -> None:
        super().__init__()
        self.load_calls = 0

    def load_projection(self, run_id: str, stage_id: str):
        self.load_calls += 1
        return super().load_projection(run_id, stage_id)


class _HaltFailingStore(InMemoryTaskPlanStore):
    def __init__(self) -> None:
        super().__init__()
        self.halt_attempts = 0

    def append_event(self, event: TaskPlanEvent) -> str:
        if event.event_type == "TASK_PLAN_HALTED":
            self.halt_attempts += 1
            raise OSError("event store unavailable")
        return super().append_event(event)


def test_authorized_inspection_exposes_only_task_plan_control_projection() -> None:
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a"),))
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=validator_context(graph),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = _CountingStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    authorizer = _InspectionAuthorizer(True)

    inspection = TaskPlanInspectionService(
        store=store,
        authorizer=authorizer,
    ).inspect(
        TaskPlanInspectionRequest(
            run_id="run",
            stage_id="dynamic_stage",
            principal_id="operator",
            tenant_id="tenant",
            authentication_evidence_ref="authn://operator/session",
        ),
        replay=TaskPlanReplayVerdict(True, canonical_payload_checksum({"replay": "ok"})),
    ).to_dict()

    assert authorizer.calls == 1
    assert store.load_calls == 1
    assert inspection["current_plan"]["plan_checksum"] == plan.plan_checksum
    assert inspection["candidate_refs"] == [candidate.candidate_checksum]
    assert inspection["tasks"] == [
        {
            "task_id": "a",
            "status": "pending",
            "depends_on": [],
            "attempts": 0,
            "active_instance_id": None,
            "worker_ref": "cap-worker@1",
            "worker_capability": "cap",
            "output_role": "role",
            "output_schema_ref": "schema://result@1",
            "result_ref": None,
            "result_checksum": None,
            "failure_reason_code": None,
        }
    ]
    assert "payload" not in str(inspection)


def test_unauthorized_inspection_fails_before_reading_task_plan_store() -> None:
    store = _CountingStore()
    authorizer = _InspectionAuthorizer(False)
    service = TaskPlanInspectionService(store=store, authorizer=authorizer)

    with pytest.raises(HarnessValidationError) as captured:
        service.inspect(
            TaskPlanInspectionRequest(
                run_id="run",
                stage_id="dynamic_stage",
                principal_id="operator",
                tenant_id="tenant",
                authentication_evidence_ref="authn://operator/session",
            )
        )

    assert captured.value.code == "task_plan_inspection_unauthorized"
    assert authorizer.calls == 1
    assert store.load_calls == 0


def test_task_plan_metrics_and_trace_are_low_cardinality_and_payload_free() -> None:
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a"),))
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=validator_context(graph),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    events = store.read_events("run", "dynamic_stage")

    samples = task_plan_metric_samples(
        store.load_projection("run", "dynamic_stage"),
        plan,
        events,
        replay_verified=True,
    )
    trace = task_plan_trace_events(events)

    assert all("run_id" not in sample.labels for sample in samples)
    assert any(sample.name == "harness_task_plan_replay_verification" for sample in samples)
    assert all("payload" not in item.to_dict() for item in trace)
    with pytest.raises(HarnessValidationError) as captured:
        TaskPlanMetricSample("bad", 1, {"run_id": "run"})
    assert captured.value.code == "task_plan_metric_label_rejected"


def test_stage_runner_rejects_policy_drift_before_recording_patch() -> None:
    graph, policy, registry = _setup()
    candidate = _candidate(graph, (_task("a"),))
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=validator_context(graph),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    events_before = store.read_events("run", "dynamic_stage")
    projection_before = store.load_projection("run", "dynamic_stage")
    drifted_policy = replace(policy, max_depth=policy.max_depth + 1)
    patch = PlanPatch.for_plan(
        plan,
        patch_id="policy-drift",
        reason_code="repair",
        source_candidate_ref="candidate://policy-drift",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.SKIP_PENDING_TASK,
                target_task_id="a",
            ),
        ),
    )
    runner = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(candidate),
        capability_registry=registry,
        store=store,
    )
    request = TaskPlanStageRequest(
        run_id="run",
        stage_binding=graph,
        context_refs={"document": "document"},
        policy=drifted_policy,
        policy_ref=drifted_policy.exact_ref,
        accepted_at="2026-08-01T00:01:00Z",
    )

    with pytest.raises(HarnessValidationError) as error:
        runner.apply_patch(request, patch)

    assert error.value.code == "task_plan_policy_mismatch"
    assert store.read_events("run", "dynamic_stage") == events_before
    assert store.load_projection("run", "dynamic_stage") == projection_before


def test_stage_request_rejects_required_role_drift_from_frozen_graph() -> None:
    stage_binding, policy, _ = _setup()
    drifted_policy = replace(
        policy,
        allowed_output_roles=("other-role",),
        required_output_roles=("other-role",),
    )

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageRequest(
            run_id="run",
            stage_binding=stage_binding,
            context_refs={"document": "document"},
            policy=drifted_policy,
            accepted_at="2026-08-01T00:01:00Z",
        )

    assert error.value.code == "task_plan_policy_mismatch"


def test_stage_runner_rejects_existing_plan_from_another_frozen_graph() -> None:
    stage_binding, policy, registry = _setup()
    candidate = _candidate(stage_binding, (_task("a"),))
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=validator_context(stage_binding),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    events_before = store.read_events("run", "dynamic_stage")
    alternate_binding = build_task_plan_stage_binding(
        graph_id="graph",
        stage_id=policy.stage_id,
        policy_ref=policy.exact_ref,
        required_output_roles=policy.required_output_roles,
        metadata_overrides={"graph_revision": "2"},
    )
    request = TaskPlanStageRequest(
        run_id="run",
        stage_binding=alternate_binding,
        context_refs={"document": "document"},
        policy=policy,
        accepted_at="2026-08-01T00:01:00Z",
    )
    patch = PlanPatch.for_plan(
        plan,
        patch_id="wrong-frozen-graph",
        reason_code="repair",
        source_candidate_ref="candidate://wrong-frozen-graph",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.SKIP_PENDING_TASK,
                target_task_id="a",
            ),
        ),
    )

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageRunner(
            candidate_builder=FakePlanCandidateBuilder(candidate),
            capability_registry=registry,
            store=store,
        ).apply_patch(request, patch)

    assert error.value.code == "task_plan_pinned_version_mismatch"
    assert store.read_events("run", "dynamic_stage") == events_before


def test_stage_runner_fails_closed_when_halt_event_cannot_be_persisted() -> None:
    graph, policy, registry = _setup()
    candidate = _candidate(
        graph,
        (_task("a", depends_on=("b",)), _task("b", depends_on=("a",))),
    )
    store = _HaltFailingStore()
    runner = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(candidate),
        capability_registry=registry,
        store=store,
    )
    request = TaskPlanStageRequest(
        run_id="run",
        stage_binding=graph,
        context_refs={"document": "document"},
        policy=policy,
        policy_ref=policy.exact_ref,
        candidate=candidate,
        accepted_at="2026-08-01T00:01:00Z",
    )

    with pytest.raises(HarnessValidationError) as error:
        runner.run(request)

    assert error.value.code == "task_plan_halt_persistence_failed"
    assert error.value.details["run_id"] == "run"
    assert error.value.details["stage_id"] == "dynamic_stage"
    assert error.value.details["reason_code"] == "task_plan_candidate_rejected"
    assert store.halt_attempts == 1
    assert not {
        "TASK_PLAN_HALTED",
        "STAGE_OUTPUT_AGGREGATED",
        "TASK_PLAN_VERIFIED",
    } & {event.event_type for event in store.read_events("run", "dynamic_stage")}
