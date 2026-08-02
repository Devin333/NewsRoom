from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.scheduler import HarnessScheduler
from framework.harness.task_plan import (
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
    TaskLifecycle,
    TaskOutputContract,
    TaskPlanPatchValidator,
    TaskPlanPolicy,
    TaskPlanPolicyRegistry,
    TaskPlanEvent,
    TaskPlanProjection,
    TaskPlanReadyDecision,
    TaskPlanReplayReducer,
    TaskPlanScheduler,
    TaskPlanValidationContext,
    TaskPlanValidator,
    TaskProjection,
    TaskResultReference,
    TaskRetryPolicy,
    TaskSpec,
    ValidatedTaskPlan,
    materialize_queue_task,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.store import TaskResultRecord
from framework.harness.workflow.binding_authority import HarnessWorkerBinding
from framework.harness.workflow.graph import HarnessContractKind, HarnessContractReference
from framework.harness.workflow.step import HarnessWorkerType
from framework.harness.workers.result import HarnessWorkerResult


ACCEPTED_AT = "2026-08-01T00:00:00Z"


class _CountingWorker:
    worker_type = HarnessWorkerType.LLM

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id
        self.worker_version = "1"
        self.calls = 0

    def execute(self, task):
        self.calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            candidate_result_ref=f"result://{task['task']['task_id']}",
            artifacts=(f"artifact://{task['task']['task_id']}",),
        )


def _graph_checksum() -> str:
    return canonical_payload_checksum({"graph": "task-plan-contract-matrix"})


def _policy(
    *,
    roles: tuple[str, ...] = ("analysis.structure",),
    required_roles: tuple[str, ...] | None = None,
    capabilities: tuple[str, ...] = ("research.structure",),
    aggregators: dict[str, str] | None = None,
    max_validation_diagnostics: int = 64,
) -> TaskPlanPolicy:
    return TaskPlanPolicy(
        policy_id="research.analysis",
        version="1",
        stage_id="dynamic_analysis_stage",
        allowed_worker_capabilities=capabilities,
        allowed_subagent_ids=(),
        allowed_tool_ids=("research.read",),
        allowed_memory_namespaces=("research.public",),
        allowed_input_refs=("document", "evidence_pack"),
        allowed_output_roles=roles,
        required_output_roles=required_roles or roles,
        allowed_output_schema_refs=tuple(f"schema://{role}@1" for role in roles),
        allowed_gate_refs=("SummarySchemaGate@1",),
        deterministic_aggregator_refs=aggregators or {},
        pinned_capability_bindings={capability: f"{capability}-worker@1" for capability in capabilities},
        required_worker_contract_refs={capability: f"{capability}-contract@1" for capability in capabilities},
        max_tasks=16,
        max_depth=8,
        max_parallelism=3,
        max_replans=2,
        max_task_attempts=2,
        max_plan_build_calls=2,
        max_plan_build_turns=4,
        max_plan_build_tool_calls=1,
        per_task_budget=TaskBudget(max_turns=2, max_tool_calls=1, max_output_tokens=256),
        aggregate_task_budget=TaskBudget(max_turns=16, max_tool_calls=8, max_output_tokens=2048),
        max_validation_diagnostics=max_validation_diagnostics,
    )


def _registry(policy: TaskPlanPolicy) -> tuple[TaskCapabilityRegistry, dict[str, _CountingWorker]]:
    workers: dict[str, _CountingWorker] = {}
    registrations = []
    role_by_capability = dict(zip(policy.allowed_worker_capabilities, policy.allowed_output_roles, strict=False))
    for capability in policy.allowed_worker_capabilities:
        worker = _CountingWorker(f"{capability}-worker")
        workers[capability] = worker
        registrations.append(
            TaskCapabilityRegistration(
                capability=capability,
                worker_binding=HarnessWorkerBinding(
                    HarnessContractReference(
                        HarnessContractKind.WORKER,
                        worker.worker_id,
                        worker.worker_version,
                    ),
                    HarnessWorkerType.LLM,
                    worker,
                ),
                worker_contract_ref=f"{capability}-contract@1",
                input_schema_ref="schema://research-input@1",
                output_schema_ref=f"schema://{role_by_capability[capability]}@1",
            )
        )
    return TaskCapabilityRegistry(registrations), workers


def _task(
    task_id: str,
    *,
    capability: str = "research.structure",
    role: str = "analysis.structure",
    depends_on: tuple[str, ...] = (),
    input_refs: tuple[str, ...] = ("document",),
    priority: int = 0,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        objective=f"Analyze {task_id}",
        worker_capability=capability,
        input_refs=input_refs,
        output_contract=TaskOutputContract(f"schema://{role}@1", role),
        acceptance_criteria=TaskAcceptanceCriteria(("SummarySchemaGate@1",)),
        depends_on=depends_on,
        requested_tools=("research.read",),
        requested_memory_namespaces=("research.public",),
        budget_request=TaskBudget(max_turns=1, max_tool_calls=1, max_output_tokens=128),
        retry_policy=TaskRetryPolicy(max_attempts=2, retryable_reason_codes=("transport",)),
        priority=priority,
    )


def _candidate(
    tasks: tuple[TaskSpec, ...],
    *,
    required_roles: tuple[str, ...] = ("analysis.structure",),
) -> PlanCandidate:
    return PlanCandidate(
        candidate_id="candidate-1",
        run_id="run-1",
        workflow_id="research.paper-analysis.dynamic",
        stage_id="dynamic_analysis_stage",
        graph_checksum=_graph_checksum(),
        input_context_refs=("document", "evidence_pack"),
        tasks=tasks,
        required_output_roles=required_roles,
        generated_by="research-planner@1",
        requested_plan_budget=PlanBuildBudget(max_builder_calls=1, max_turns=2),
        requested_max_parallelism=2,
    )


def _context(policy: TaskPlanPolicy, *, future_refs: tuple[str, ...] = ()) -> TaskPlanValidationContext:
    return TaskPlanValidationContext(
        run_id="run-1",
        workflow_id="research.paper-analysis.dynamic",
        stage_id="dynamic_analysis_stage",
        graph_checksum=_graph_checksum(),
        available_input_refs=("document", "evidence_pack"),
        future_stage_input_refs=future_refs,
        registered_gate_refs=policy.allowed_gate_refs,
        registered_aggregator_refs=tuple(policy.deterministic_aggregator_refs.values()),
        dynamic_stage_declared=True,
    )


def _accepted_plan(
    tasks: tuple[TaskSpec, ...],
    *,
    policy: TaskPlanPolicy | None = None,
) -> tuple[ValidatedTaskPlan, TaskPlanPolicy, TaskCapabilityRegistry, dict[str, _CountingWorker]]:
    selected_policy = policy or _policy()
    registry, workers = _registry(selected_policy)
    candidate = _candidate(tasks, required_roles=selected_policy.required_output_roles)
    plan = TaskPlanValidator().accept(
        candidate,
        selected_policy,
        registry,
        context=_context(selected_policy),
        accepted_at=ACCEPTED_AT,
    )
    return plan, selected_policy, registry, workers


def test_contracts_are_immutable_canonical_and_fail_closed_on_tamper():
    task = _task("structure")
    candidate = _candidate((task,))
    policy = _policy()
    registry, _ = _registry(policy)
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=_context(policy),
        accepted_at=ACCEPTED_AT,
    )
    result_ref = TaskResultReference(
        result_ref="result://structure",
        result_checksum=canonical_payload_checksum({"result": "structure"}),
        output_role="analysis.structure",
        output_schema_ref="schema://analysis.structure@1",
    )
    projection = TaskPlanProjection(
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_checksum=plan.plan_checksum,
        policy_ref=plan.policy_ref,
        tasks=(
            TaskProjection(
                task_id="structure",
                task_definition_checksum=plan.tasks[0].task_definition_checksum,
                status=TaskLifecycle.SUCCEEDED,
                attempts=1,
                active_instance_id="instance-1",
                result=result_ref,
            ),
        ),
        consumed_budget={"consumed_max_turns": 1},
        last_sequence=4,
    )
    patch = PlanPatch(
        patch_id="patch-1",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="missing-output",
        source_candidate_ref="candidate://patch-1",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.ADD_REPLACEMENT_TASK,
                target_task_id="structure",
                replacement_task=replace(task, task_id="structure-replacement"),
            ),
        ),
    )

    models = (task, candidate, policy, plan.tasks[0], plan, result_ref, projection, patch)
    for model in models:
        restored = type(model).from_dict(model.to_dict())
        assert restored == model
        checksum_field = next(name for name in model.__dataclass_fields__ if name.endswith("checksum"))
        with pytest.raises(FrozenInstanceError):
            setattr(model, checksum_field, "sha256:" + "0" * 64)

    tampered = candidate.to_dict()
    tampered["generated_by"] = "attacker@1"
    with pytest.raises(HarnessValidationError, match="checksum"):
        PlanCandidate.from_dict(tampered)

    unsupported = candidate.to_dict()
    unsupported["schema_version"] = "newsroom.harness-task-plan-candidate/v999"
    with pytest.raises(HarnessValidationError) as error:
        PlanCandidate.from_dict(unsupported)
    assert error.value.code == "unsupported_task_plan_schema"

    unknown = candidate.to_dict()
    unknown["unknown"] = True
    with pytest.raises(HarnessValidationError) as error:
        PlanCandidate.from_dict(unknown)
    assert error.value.code == "invalid_task_plan_payload_fields"


@pytest.mark.parametrize(
    "nested",
    (
        {"route": "quality_gate"},
        {"diagnostics": [{"quality_passed": True}]},
        {"deep": {"publish_artifact": "artifact://unsafe"}},
        {"tool_authorization": {"research.read": True}},
    ),
)
def test_candidate_forbidden_control_fields_are_rejected_recursively(nested):
    with pytest.raises(HarnessValidationError) as error:
        replace(_task("structure"), metadata=nested)
    assert error.value.code == "task_plan_forbidden_candidate_field"


def test_policy_registry_requires_exact_unique_compatible_versions():
    policy = _policy()
    registry = TaskPlanPolicyRegistry((policy,))
    assert registry.resolve("research.analysis@1", stage_id="dynamic_analysis_stage") is policy
    with pytest.raises(HarnessValidationError) as error:
        registry.resolve("research.analysis@latest")
    assert error.value.code == "task_plan_inexact_reference"
    with pytest.raises(HarnessValidationError) as error:
        registry.resolve("research.analysis@2")
    assert error.value.code == "unknown_task_plan_policy"
    with pytest.raises(HarnessValidationError) as error:
        TaskPlanPolicyRegistry((policy, policy))
    assert error.value.code == "duplicate_task_plan_policy"


def test_validated_plan_policy_checksum_is_durable_and_legacy_replay_is_read_only() -> None:
    plan, policy, registry, _ = _accepted_plan((_task("structure"),))
    assert plan.policy_checksum == policy.policy_checksum
    assert ValidatedTaskPlan.from_dict(plan.to_dict()) == plan

    legacy_payload = plan.to_dict()
    legacy_payload.pop("policy_checksum")
    legacy_payload["plan_checksum"] = canonical_payload_checksum(
        {
            key: value
            for key, value in legacy_payload.items()
            if key != "plan_checksum"
        }
    )
    legacy_plan = ValidatedTaskPlan.from_dict(legacy_payload)
    assert legacy_plan.policy_checksum is None
    assert legacy_plan.to_dict() == legacy_payload

    store = InMemoryTaskPlanStore()
    candidate = _candidate(tuple(item.task for item in legacy_plan.tasks))
    store.append_candidate(candidate)
    legacy_plan = replace(
        legacy_plan,
        source_candidate_ref=candidate.candidate_checksum,
    )
    store.accept_plan(legacy_plan)
    patch = PlanPatch(
        patch_id="legacy-policy-patch",
        run_id=legacy_plan.run_id,
        stage_id=legacy_plan.stage_id,
        base_plan_id=legacy_plan.plan_id,
        base_plan_version=legacy_plan.version,
        reason_code="repair",
        source_candidate_ref="candidate://legacy-policy-patch",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.SKIP_PENDING_TASK,
                target_task_id="structure",
            ),
        ),
    )
    with pytest.raises(HarnessValidationError) as error:
        TaskPlanPatchValidator().apply(
            legacy_plan,
            patch,
            store.load_projection(legacy_plan.run_id, legacy_plan.stage_id),
            policy,
            registry,
            accepted_at="2026-08-01T00:02:00Z",
            available_input_refs=("document", "evidence_pack"),
        )
    assert error.value.code == "task_plan_policy_mismatch"


def test_validator_accepts_optional_required_role_but_rejects_implicit_task_dataflow():
    policy = _policy(
        roles=("analysis.structure", "analysis.helper"),
        required_roles=("analysis.structure",),
        capabilities=("research.structure", "research.helper"),
    )
    registry, workers = _registry(policy)
    valid = _candidate(
        (
            _task("structure"),
            _task("helper", capability="research.helper", role="analysis.helper"),
        ),
        required_roles=("analysis.structure", "analysis.helper"),
    )
    accepted = TaskPlanValidator().validate(
        valid,
        policy=policy,
        capabilities=registry,
        context=_context(policy),
    )
    assert accepted.accepted
    assert sum(worker.calls for worker in workers.values()) == 0

    implicit = _candidate(
        (
            _task("structure"),
            _task(
                "helper",
                capability="research.helper",
                role="analysis.helper",
                input_refs=("task:structure",),
            ),
        ),
        required_roles=("analysis.structure", "analysis.helper"),
    )
    rejected = TaskPlanValidator().validate(
        implicit,
        policy=policy,
        capabilities=registry,
        context=_context(policy),
    )
    assert not rejected.accepted
    assert "task_plan_task_input_dependency_missing" in {
        item.code for item in rejected.diagnostics
    }
    assert sum(worker.calls for worker in workers.values()) == 0


@pytest.mark.parametrize(
    "task_ref",
    ("task:structure/output", "task://structure/output"),
)
def test_validator_normalizes_task_reference_forms(task_ref: str) -> None:
    policy = _policy(
        roles=("analysis.structure", "analysis.helper"),
        required_roles=("analysis.structure", "analysis.helper"),
        capabilities=("research.structure", "research.helper"),
    )
    registry, _ = _registry(policy)
    candidate = _candidate(
        (
            _task("structure"),
            _task(
                "helper",
                capability="research.helper",
                role="analysis.helper",
                depends_on=("structure",),
                input_refs=(task_ref,),
            ),
        ),
        required_roles=policy.required_output_roles,
    )

    result = TaskPlanValidator().validate(
        candidate,
        policy=policy,
        capabilities=registry,
        context=_context(policy),
    )

    assert result.accepted


def test_validator_authorizes_each_mixed_input_reference_independently() -> None:
    policy = _policy(
        roles=("analysis.structure", "analysis.helper"),
        required_roles=("analysis.structure", "analysis.helper"),
        capabilities=("research.structure", "research.helper"),
    )
    registry, _ = _registry(policy)
    candidate = _candidate(
        (
            _task("structure"),
            _task(
                "helper",
                capability="research.helper",
                role="analysis.helper",
                depends_on=("structure",),
                input_refs=("task://structure/output", "secret://tenant-private"),
            ),
        ),
        required_roles=policy.required_output_roles,
    )
    context = replace(
        _context(policy),
        available_input_refs=("document", "evidence_pack", "secret://tenant-private"),
    )

    result = TaskPlanValidator().validate(
        candidate,
        policy=policy,
        capabilities=registry,
        context=context,
    )

    assert not result.accepted
    assert "task_plan_input_reference_unavailable" in {
        item.code for item in result.diagnostics
    }


def test_initial_candidate_rejects_dependency_depth_beyond_policy() -> None:
    policy = replace(
        _policy(
            roles=("analysis.structure", "analysis.helper", "analysis.repair"),
            required_roles=("analysis.structure",),
            capabilities=("research.structure", "research.helper", "research.repair"),
        ),
        max_depth=1,
    )
    registry, _ = _registry(policy)
    candidate = _candidate(
        (
            _task("a"),
            _task(
                "b",
                capability="research.helper",
                role="analysis.helper",
                depends_on=("a",),
                input_refs=("task:a/output",),
            ),
            _task(
                "c",
                capability="research.repair",
                role="analysis.repair",
                depends_on=("b",),
                input_refs=("task://b/output",),
            ),
        ),
        required_roles=policy.required_output_roles,
    )

    result = TaskPlanValidator().validate(
        candidate,
        policy=policy,
        capabilities=registry,
        context=_context(policy),
    )

    assert not result.accepted
    assert "task_plan_depth_exceeded" in {item.code for item in result.diagnostics}


def test_scheduler_queue_projection_and_result_identity_are_deterministic():
    policy = _policy(
        roles=("analysis.structure", "analysis.helper"),
        required_roles=("analysis.structure", "analysis.helper"),
        capabilities=("research.structure", "research.helper"),
    )
    plan, policy, _, _ = _accepted_plan(
        (
            _task("z-root", priority=1),
            _task("a-root", capability="research.helper", role="analysis.helper"),
        ),
        policy=policy,
    )
    candidate = _candidate(tuple(item.task for item in plan.tasks), required_roles=policy.required_output_roles)
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    scheduler = TaskPlanScheduler()
    decision = scheduler.next_ready_tasks(
        store.load_projection(plan.run_id, plan.stage_id),
        10,
        plan=plan,
        policy=policy,
        worker_capacity=1,
        available_input_refs=("document", "evidence_pack"),
    )
    assert [instance.task_id for instance in decision.task_instances] == ["a-root"]
    instance = decision.task_instances[0]
    queue_task = materialize_queue_task(instance, workflow_id=plan.workflow_id)
    assert queue_task.payload == {}
    assert "depends_on" not in queue_task.metadata
    assert queue_task.metadata["plan_version"] == 1

    projection = scheduler.reserve_ready_tasks(store.load_projection(plan.run_id, plan.stage_id), decision)
    projection = scheduler.mark_dispatched(projection, instance)
    store.update_projection(projection)
    accepted = TaskResultRecord(
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
        binding_checksum=next(
            item.binding_checksum for item in plan.tasks if item.task_id == instance.task_id
        ),
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://a-root",
        output_refs=("artifact://a-root",),
        output_roles=("analysis.helper",),
        output_schema_ref="schema://analysis.helper@1",
        usage={"turns": 1},
    )
    assert store.append_result(accepted) == store.append_result(accepted)

    wrong_attempt = replace(accepted, attempt=accepted.attempt + 1)
    with pytest.raises(HarnessValidationError) as error:
        store.append_result(wrong_attempt)
    assert error.value.code == "task_plan_wrong_attempt"

    wrong_binding = replace(accepted, task_instance_id="different-instance", worker_ref="wrong-worker@1")
    with pytest.raises(HarnessValidationError) as error:
        store.append_result(wrong_binding)
    assert error.value.code in {"task_plan_wrong_binding", "task_plan_wrong_attempt"}


def test_harness_scheduler_and_store_commit_terminal_result_with_budget_parity():
    plan, policy, _, _ = _accepted_plan((_task("structure"),))
    candidate = _candidate(
        tuple(item.task for item in plan.tasks),
        required_roles=policy.required_output_roles,
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    scheduler = HarnessScheduler()
    decision = scheduler.next_task_plan_decision(
        store.load_projection(plan.run_id, plan.stage_id),
        1,
        plan=plan,
        policy=policy,
        available_input_refs=("document", "evidence_pack"),
    )
    instance = decision.task_instances[0]

    projection = scheduler.reserve_task_plan_tasks(
        store.load_projection(plan.run_id, plan.stage_id),
        decision,
    )
    for sequence, event_type in enumerate(
        ("TASK_READY", "TASK_DISPATCHED", "TASK_STARTED"),
        start=3,
    ):
        if event_type == "TASK_DISPATCHED":
            projection = scheduler.mark_task_plan_dispatched(projection, instance)
        elif event_type == "TASK_STARTED":
            projection = scheduler.mark_task_plan_started(projection, instance)
        projection = replace(projection, last_sequence=sequence)
        store.commit_event(
            TaskPlanEvent(
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
            ),
            projection,
        )

    result = TaskResultRecord(
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
        binding_checksum=plan.tasks[0].binding_checksum,
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://structure",
        output_refs=("artifact://structure",),
        output_roles=("analysis.structure",),
        output_schema_ref="schema://analysis.structure@1",
        usage={"turns": 1, "tool_calls": 1},
    )
    store.append_result(result)

    events = store.read_events(plan.run_id, plan.stage_id)
    projection = store.load_projection(plan.run_id, plan.stage_id)
    assert [event.event_type for event in events[-2:]] == [
        "TASK_RESULT_ACCEPTED",
        "TASK_COMPLETED",
    ]
    assert projection.last_sequence == len(events) == 7
    assert projection.consumed_budget["reserved_max_turns"] == 0
    assert projection.consumed_budget["consumed_max_turns"] == 1
    assert projection.consumed_budget["consumed_max_tool_calls"] == 1
    replay = TaskPlanReplayReducer().replay((plan,), events, results=(result,))
    assert replay.projection.projection_checksum == projection.projection_checksum


def test_patch_history_is_immutable_and_running_tasks_cannot_be_edited():
    policy = _policy(
        roles=("analysis.structure", "analysis.helper"),
        required_roles=("analysis.structure",),
        capabilities=("research.structure", "research.helper"),
    )
    plan, policy, registry, _ = _accepted_plan(
        (
            _task("structure"),
            _task("helper", capability="research.helper", role="analysis.helper"),
        ),
        policy=policy,
    )
    candidate = _candidate(tuple(item.task for item in plan.tasks), required_roles=policy.required_output_roles)
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    patch = PlanPatch(
        patch_id="patch-1",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="repair",
        source_candidate_ref="candidate://repair",
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
    base_projection = store.load_projection(plan.run_id, plan.stage_id)
    base_projection = replace(
        base_projection,
        tasks=tuple(
            replace(item, status=TaskLifecycle.FAILED, failure_reason_code="retry-exhausted")
            if item.task_id == "helper"
            else item
            for item in base_projection.tasks
        ),
    )
    store.update_projection(base_projection)
    next_plan = TaskPlanPatchValidator().apply(
        plan,
        patch,
        base_projection,
        policy,
        registry,
        accepted_at="2026-08-01T00:01:00Z",
        available_input_refs=("document", "evidence_pack"),
    )
    store.append_patch(patch, accepted=True)
    store.accept_plan(next_plan)
    assert store.plan(plan.run_id, plan.stage_id, 1) == plan
    assert store.plan(plan.run_id, plan.stage_id, 2) == next_plan
    assert next_plan.parent_plan_id == plan.plan_id
    assert next_plan.graph_checksum == plan.graph_checksum

    projection = store.load_projection(plan.run_id, plan.stage_id)
    replacement = next(item for item in next_plan.tasks if item.task_id == "helper-replacement")
    instance = TaskPlanScheduler().next_ready_tasks(
        projection,
        1,
        plan=next_plan,
        policy=policy,
        available_input_refs=("document", "evidence_pack"),
    ).task_instances[0]
    running = TaskPlanScheduler.mark_started(
        TaskPlanScheduler.mark_dispatched(
            TaskPlanScheduler().reserve_ready_tasks(
                projection,
                TaskPlanReadyDecision((instance,)),
            ),
            instance,
        ),
        instance,
    )
    assert replacement.task_id in {item.task_id for item in next_plan.tasks}
    stale_patch = replace(
        patch,
        patch_id="patch-2",
        base_plan_id=next_plan.plan_id,
        base_plan_version=next_plan.version,
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.UPDATE_PENDING_DEPENDENCY,
                target_task_id=instance.task_id,
                depends_on=("structure",),
            ),
        ),
    )
    with pytest.raises(HarnessValidationError) as error:
        TaskPlanPatchValidator().apply(
            next_plan,
            stale_patch,
            running,
            policy,
            registry,
            accepted_at="2026-08-01T00:02:00Z",
            available_input_refs=("document", "evidence_pack"),
        )
    assert error.value.code == "task_plan_patch_task_not_pending"


def test_patch_rejects_policy_reference_and_checksum_drift() -> None:
    plan, policy, registry, _ = _accepted_plan((_task("structure"),))
    store = InMemoryTaskPlanStore()
    candidate = _candidate(tuple(item.task for item in plan.tasks))
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    projection = store.load_projection(plan.run_id, plan.stage_id)
    patch = PlanPatch(
        patch_id="policy-drift-patch",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="repair",
        source_candidate_ref="candidate://policy-drift",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.SKIP_PENDING_TASK,
                target_task_id="structure",
            ),
        ),
    )

    for supplied_policy in (
        replace(policy, version="2"),
        replace(policy, max_depth=policy.max_depth + 1),
    ):
        with pytest.raises(HarnessValidationError) as error:
            TaskPlanPatchValidator().apply(
                plan,
                patch,
                projection,
                supplied_policy,
                registry,
                accepted_at="2026-08-01T00:02:00Z",
                available_input_refs=("document", "evidence_pack"),
            )
        assert error.value.code == "task_plan_policy_mismatch"


def test_patch_rejects_dependency_depth_beyond_policy_with_shared_memo() -> None:
    policy = replace(
        _policy(
            roles=("analysis.structure", "analysis.helper", "analysis.repair"),
            required_roles=("analysis.structure",),
            capabilities=("research.structure", "research.helper", "research.repair"),
        ),
        max_depth=1,
    )
    plan, policy, registry, _ = _accepted_plan(
        (
            _task("a"),
            _task(
                "b",
                capability="research.helper",
                role="analysis.helper",
                depends_on=("a",),
                input_refs=("task:a/output",),
            ),
        ),
        policy=policy,
    )
    store = InMemoryTaskPlanStore()
    candidate = _candidate(
        tuple(item.task for item in plan.tasks),
        required_roles=policy.required_output_roles,
    )
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    projection = store.load_projection(plan.run_id, plan.stage_id)
    projection = replace(
        projection,
        tasks=tuple(
            replace(item, status=TaskLifecycle.FAILED, failure_reason_code="repair")
            if item.task_id == "b"
            else item
            for item in projection.tasks
        ),
    )
    patch = PlanPatch(
        patch_id="deep-patch",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="repair",
        source_candidate_ref="candidate://deep-patch",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.ADD_REPLACEMENT_TASK,
                target_task_id="b",
                replacement_task=_task(
                    "c",
                    capability="research.repair",
                    role="analysis.repair",
                    depends_on=("b",),
                    input_refs=("task://b/output",),
                ),
            ),
        ),
    )

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanPatchValidator().apply(
            plan,
            patch,
            projection,
            policy,
            registry,
            accepted_at="2026-08-01T00:02:00Z",
            available_input_refs=("document", "evidence_pack"),
        )

    assert error.value.code == "task_plan_depth_exceeded"


def test_replay_uses_only_recorded_evidence_and_matches_projection_checksum():
    plan, policy, _, workers = _accepted_plan((_task("structure"),))
    candidate = _candidate(tuple(item.task for item in plan.tasks), required_roles=policy.required_output_roles)
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    plan = replace(plan, source_candidate_ref=candidate.candidate_checksum)
    store.accept_plan(plan)
    scheduler = TaskPlanScheduler()
    decision = scheduler.next_ready_tasks(
        store.load_projection(plan.run_id, plan.stage_id),
        1,
        plan=plan,
        policy=policy,
        available_input_refs=("document", "evidence_pack"),
    )
    instance = decision.task_instances[0]
    projection = scheduler.reserve_ready_tasks(store.load_projection(plan.run_id, plan.stage_id), decision)
    projection = scheduler.mark_dispatched(projection, instance)
    store.append_event(
        TaskPlanEvent(
            "TASK_READY",
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
            sequence=3,
        )
    )
    store.append_event(
        TaskPlanEvent(
            "TASK_DISPATCHED",
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
            sequence=4,
        )
    )
    store.update_projection(replace(projection, last_sequence=4))
    result = TaskResultRecord(
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
        binding_checksum=next(
            item.binding_checksum for item in plan.tasks if item.task_id == instance.task_id
        ),
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://structure",
        output_refs=("artifact://structure",),
        output_roles=("analysis.structure",),
        output_schema_ref="schema://analysis.structure@1",
    )
    store.append_result(result)
    live_calls = sum(worker.calls for worker in workers.values())
    replay = TaskPlanReplayReducer().reduce(
        plan,
        store.read_events(plan.run_id, plan.stage_id),
        results=(result,),
    )
    assert sum(worker.calls for worker in workers.values()) == live_calls == 0
    current = store.load_projection(plan.run_id, plan.stage_id)
    assert replay.tasks == current.tasks
    assert replay.last_sequence == current.last_sequence
