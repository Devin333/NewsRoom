from __future__ import annotations

from collections.abc import Mapping

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.task_plan import (
    FakePlanCandidateBuilder,
    InMemoryTaskPlanStore,
    PlanBuildBudget,
    PlanCandidate,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
    TaskOutputContract,
    TaskPlanPolicy,
    TaskPlanStageIdentity,
    TaskPlanStageRequest,
    TaskPlanStageRunner,
    TaskPlanValidationContext,
    TaskPlanValidator,
    TaskSpec,
)
from tests.fixtures.task_plan import build_task_plan_stage_binding


class _Worker:
    worker_id = "receipt-worker"
    worker_version = "1"
    worker_type = HarnessWorkerType.LLM

    def execute(self, _task):
        raise AssertionError("receipt history tests do not execute workers")


def _runner_fixture():
    policy = TaskPlanPolicy(
        policy_id="spawn.receipt-history",
        version="1",
        stage_id="receipt-stage",
        allowed_worker_capabilities=("receipt-capability",),
        allowed_subagent_ids=(),
        allowed_tool_ids=(),
        allowed_memory_namespaces=(),
        allowed_input_refs=("document",),
        allowed_output_roles=("analysis.receipt",),
        required_output_roles=("analysis.receipt",),
        allowed_output_schema_refs=("schema://receipt@1",),
        allowed_gate_refs=("ReceiptGate@1",),
        deterministic_aggregator_refs={},
        pinned_capability_bindings={"receipt-capability": "receipt-worker@1"},
        required_worker_contract_refs={"receipt-capability": "receipt-contract@1"},
        max_tasks=1,
        max_depth=1,
        max_parallelism=1,
        max_replans=0,
        max_task_attempts=1,
        max_plan_build_calls=1,
        max_plan_build_turns=1,
        max_plan_build_tool_calls=0,
        per_task_budget=TaskBudget(max_turns=1),
        aggregate_task_budget=TaskBudget(max_turns=1),
    )
    binding = build_task_plan_stage_binding(
        graph_id="spawn.receipt-history",
        stage_id=policy.stage_id,
        policy_ref=policy.exact_ref,
        required_output_roles=policy.required_output_roles,
        input_keys=("document",),
    )
    registry = TaskCapabilityRegistry(
        (
            TaskCapabilityRegistration(
                "receipt-capability",
                HarnessWorkerBinding(
                    HarnessContractReference(
                        HarnessContractKind.WORKER,
                        "receipt-worker",
                        "1",
                    ),
                    HarnessWorkerType.LLM,
                    _Worker(),
                ),
                "receipt-contract@1",
                "schema://input@1",
                "schema://receipt@1",
            ),
        )
    )
    candidate = PlanCandidate.for_stage(
        stage_identity=TaskPlanStageIdentity("receipt-run", binding),
        candidate_id="receipt-candidate",
        input_context_refs=("document",),
        tasks=(
            TaskSpec(
                task_id="receipt-task",
                objective="persist a spawn receipt",
                worker_capability="receipt-capability",
                input_refs=("document",),
                output_contract=TaskOutputContract(
                    "schema://receipt@1",
                    "analysis.receipt",
                ),
                acceptance_criteria=TaskAcceptanceCriteria(("ReceiptGate@1",)),
                budget_request=TaskBudget(max_turns=1),
                retry_policy={"max_attempts": 1, "retryable_reason_codes": []},
            ),
        ),
        required_output_roles=("analysis.receipt",),
        generated_by="receipt-planner@1",
        requested_plan_budget=PlanBuildBudget(max_builder_calls=1, max_turns=1),
        requested_max_parallelism=1,
    )
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=TaskPlanValidationContext(
            run_id="receipt-run",
            stage_binding=binding,
            available_input_refs=("document",),
            registered_gate_refs=("ReceiptGate@1",),
        ),
        accepted_at="2026-09-06T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    request = TaskPlanStageRequest(
        run_id=plan.run_id,
        stage_binding=binding,
        context_refs={"document": "document"},
        policy=policy,
        candidate=candidate,
        accepted_at="2026-09-06T00:00:00Z",
    )
    runner = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(candidate),
        capability_registry=registry,
        store=store,
    )
    return runner, request, plan, store


def _confirmed_receipt() -> dict[str, object]:
    return {
        "event_type": "TASK_ATTEMPT_SPAWN_CONFIRMED",
        "group_id": "group-1",
        "wave_id": "wave-1",
        "task_id": "receipt-task",
        "task_instance_id": "task-instance-1",
        "attempt": 1,
        "operation_key": "spawn-operation-1",
        "spawn_status": "SPAWN_CONFIRMED",
        "child_id": "child-1",
        "idempotency_key": "spawn-operation-1",
    }


def test_identical_spawn_receipt_redelivery_is_reused() -> None:
    runner, request, plan, store = _runner_fixture()
    receipt = _confirmed_receipt()

    runner._record_parallel_events(request, plan, (receipt, dict(receipt)))
    history = store.read_events(plan.run_id, plan.stage_id)

    runner._record_parallel_events(request, plan, (dict(receipt),))

    assert [event.event_type for event in history].count(
        "TASK_ATTEMPT_SPAWN_CONFIRMED"
    ) == 1
    assert store.read_events(plan.run_id, plan.stage_id) == history


@pytest.mark.parametrize(
    "changes",
    (
        {"event_type": "TASK_ATTEMPT_SPAWN_UNKNOWN", "spawn_status": "SPAWN_UNKNOWN"},
        {"child_id": "child-2"},
        {"task_id": "other-task"},
    ),
)
def test_conflicting_spawn_receipt_is_rejected_before_history_write(
    changes: Mapping[str, object],
) -> None:
    runner, request, plan, store = _runner_fixture()
    receipt = _confirmed_receipt()
    runner._record_parallel_events(request, plan, (receipt,))
    history = store.read_events(plan.run_id, plan.stage_id)
    conflicting = {**receipt, **changes}
    if conflicting["event_type"] == "TASK_ATTEMPT_SPAWN_UNKNOWN":
        conflicting.pop("child_id")

    with pytest.raises(HarnessValidationError) as error:
        runner._record_parallel_events(request, plan, (conflicting,))

    assert error.value.code == "task_plan_event_history_conflict"
    assert store.read_events(plan.run_id, plan.stage_id) == history
