from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan import (
    InMemoryTaskPlanStore,
    PlanBuildBudget,
    PlanCandidate,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
    TaskLifecycle,
    TaskOutputContract,
    TaskPlanCheckpoint,
    TASK_PLAN_CHECKPOINT_SCHEMA_V1,
    TaskPlanEvent,
    TaskPlanPolicy,
    TaskPlanRecoveryService,
    TaskPlanReplayReducer,
    TASK_PLAN_REPLAY_REDUCER_VERSION_V1,
    TaskPlanValidationContext,
    TaskPlanValidator,
    TaskResultRecord,
    TaskRetryPolicy,
    TaskSpec,
    task_instance_for_attempt,
)
from framework.harness.task_plan.canonical import canonical_payload_checksum
from framework.harness.task_plan.models import PlanPatch, PlanPatchOperation, PlanPatchOperationType
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.graph.activity import HarnessWorkerType
from framework.harness.workers.result import HarnessWorkerResult
from tests.fixtures.task_plan import build_task_plan_stage_binding


class _NeverCalledWorker:
    worker_id = "recovery-worker"
    worker_version = "1"
    worker_type = HarnessWorkerType.LLM

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, task):
        self.calls += 1
        return HarnessWorkerResult(status="succeeded", candidate_result_ref="result://unexpected")


def _history_fixture():
    policy = TaskPlanPolicy(
        policy_id="recovery.task-plan",
        version="1",
        stage_id="dynamic_stage",
        allowed_worker_capabilities=("recover",),
        allowed_subagent_ids=(),
        allowed_tool_ids=(),
        allowed_memory_namespaces=(),
        allowed_input_refs=("document",),
        allowed_output_roles=("analysis.result",),
        required_output_roles=("analysis.result",),
        allowed_output_schema_refs=("schema://analysis.result@1",),
        allowed_gate_refs=("ResultGate@1",),
        deterministic_aggregator_refs={},
        pinned_capability_bindings={"recover": "recovery-worker@1"},
        required_worker_contract_refs={"recover": "recovery-worker-contract@1"},
        max_tasks=2,
        max_depth=2,
        max_parallelism=1,
        max_replans=1,
        max_task_attempts=2,
        max_plan_build_calls=1,
        max_plan_build_turns=1,
        max_plan_build_tool_calls=0,
        per_task_budget=TaskBudget(max_turns=1, max_output_tokens=64),
        aggregate_task_budget=TaskBudget(max_turns=2, max_output_tokens=128),
    )
    stage_binding = build_task_plan_stage_binding(
        workflow_id="recovery-workflow",
        stage_id=policy.stage_id,
        policy_ref=policy.exact_ref,
        required_output_roles=policy.required_output_roles,
        input_keys=("document",),
    )
    worker = _NeverCalledWorker()
    registry = TaskCapabilityRegistry(
        (
            TaskCapabilityRegistration(
                capability="recover",
                worker_binding=HarnessWorkerBinding(
                    HarnessContractReference(
                        HarnessContractKind.WORKER,
                        worker.worker_id,
                        worker.worker_version,
                    ),
                    HarnessWorkerType.LLM,
                    worker,
                ),
                worker_contract_ref="recovery-worker-contract@1",
                input_schema_ref="schema://recovery-input@1",
                output_schema_ref="schema://analysis.result@1",
            ),
        )
    )
    task = TaskSpec(
        task_id="recover-task",
        objective="Recover from recorded evidence",
        worker_capability="recover",
        input_refs=("document",),
        output_contract=TaskOutputContract(
            "schema://analysis.result@1",
            "analysis.result",
        ),
        acceptance_criteria=TaskAcceptanceCriteria(("ResultGate@1",)),
        budget_request=TaskBudget(max_turns=1, max_output_tokens=64),
        retry_policy=TaskRetryPolicy(max_attempts=2),
    )
    candidate = PlanCandidate(
        candidate_id="recovery-candidate",
        run_id="recovery-run",
        workflow_id="recovery-workflow",
        stage_id="dynamic_stage",
        graph_checksum=stage_binding.graph_checksum,
        input_context_refs=("document",),
        tasks=(task,),
        required_output_roles=("analysis.result",),
        generated_by="recovery-planner@1",
        requested_plan_budget=PlanBuildBudget(max_builder_calls=1, max_turns=1),
    )
    plan = TaskPlanValidator().accept(
        candidate,
        policy,
        registry,
        context=TaskPlanValidationContext(
            run_id=candidate.run_id,
            stage_binding=stage_binding,
            available_input_refs=("document",),
            registered_gate_refs=policy.allowed_gate_refs,
        ),
        accepted_at="2026-08-01T00:00:00Z",
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(candidate)
    store.accept_plan(plan)
    return plan, tuple(store.read_events(plan.run_id, plan.stage_id)), worker


def _lifecycle_event(event_type, sequence, plan, instance, *, input_checksum=None, output_refs=(), payload=None):
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
        input_checksum=input_checksum or instance.task_definition_checksum,
        output_refs=output_refs,
        payload=payload or {},
        sequence=sequence,
    )


def _result(plan, instance):
    definition = plan.tasks[0]
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
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://recover-task",
        output_refs=("artifact://recover-task",),
        output_roles=("analysis.result",),
        output_schema_ref="schema://analysis.result@1",
        verified_gate_refs=("ResultGate@1",),
        gate_evidence_refs=("evidence://result-gate",),
    )


def test_checkpoint_roundtrip_and_missing_queue_projection_recovery_are_offline():
    plan, base_events, worker = _history_fixture()
    instance = task_instance_for_attempt(plan, "recover-task", 1)
    events = (
        *base_events,
        _lifecycle_event("TASK_READY", 3, plan, instance),
    )
    report = TaskPlanReplayReducer().replay((plan,), events)
    checkpoint = TaskPlanCheckpoint.from_replay(
        "checkpoint-1",
        plan,
        report,
        created_at="2026-08-01T00:00:01Z",
    )
    restored = TaskPlanCheckpoint.from_dict(checkpoint.to_dict())

    assert report.reducer_version == TASK_PLAN_REPLAY_REDUCER_VERSION_V1
    assert report.replay_checksum == (
        "sha256:e5ad569f4c4aaf92dd634a4041399751491d52c4485e6e3c736b732840e3cb98"
    )
    assert checkpoint.schema_version == TASK_PLAN_CHECKPOINT_SCHEMA_V1
    assert checkpoint.checkpoint_checksum == (
        "sha256:b4147439158783492ae0efaa23b48cb32b64896815c2688c430c772b9aac0d66"
    )
    assert set(checkpoint.to_dict()) == {
        "accepted_output_refs",
        "active_task_instances",
        "aggregate_checksum",
        "aggregate_ref",
        "budget_snapshot",
        "checkpoint_checksum",
        "checkpoint_id",
        "created_at",
        "event_history_checksum",
        "graph_checksum",
        "last_sequence",
        "pending_terminal_results",
        "plan_checksum",
        "plan_id",
        "plan_version",
        "policy_ref",
        "projection",
        "ready_order",
        "reducer_version",
        "replan_count",
        "replay_checksum",
        "retry_counts",
        "run_id",
        "schema_version",
        "stage_id",
        "workflow_id",
    }

    recovery = TaskPlanRecoveryService().recover(
        (plan,),
        events,
        checkpoint=restored,
    )

    assert recovery.checkpoint_verified is True
    assert recovery.recovered_from_sequence == 3
    assert len(recovery.missing_queue_projections) == 1
    queue_task = recovery.missing_queue_projections[0]
    assert queue_task.task_id == instance.task_instance_id
    assert queue_task.payload == {}
    assert queue_task.metadata["fencing_token"] == instance.fencing_token
    assert worker.calls == 0


def test_legacy_replay_rejects_plan_history_with_changed_graph_checksum():
    plan, events, _ = _history_fixture()
    changed_graph_plan = replace(
        plan,
        plan_id="recover-plan-2",
        version=2,
        parent_plan_id=plan.plan_id,
        graph_checksum="sha256:" + "f" * 64,
    )

    with pytest.raises(HarnessValidationError) as captured:
        TaskPlanReplayReducer().replay(
            (plan, changed_graph_plan),
            events,
            require_latest_plan=False,
        )

    assert captured.value.code == "task_plan_replay_identity_mismatch"


def test_recovery_preserves_committed_result_until_terminal_event_without_redispatch():
    plan, base_events, worker = _history_fixture()
    instance = task_instance_for_attempt(plan, "recover-task", 1)
    result = _result(plan, instance)
    events_before_terminal = (
        *base_events,
        _lifecycle_event("TASK_READY", 3, plan, instance),
        _lifecycle_event("TASK_DISPATCHED", 4, plan, instance),
        _lifecycle_event("TASK_STARTED", 5, plan, instance),
        _lifecycle_event(
            "TASK_RESULT_ACCEPTED",
            6,
            plan,
            instance,
            output_refs=result.output_refs,
            payload={
                "result_ref": result.result_ref,
                "result_checksum": result.result_checksum,
                "gate_refs": list(result.verified_gate_refs),
                "gate_evidence_refs": list(result.gate_evidence_refs),
            },
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        TaskPlanReplayReducer().replay(
            (plan,),
            events_before_terminal,
            results=(result,),
        )
    assert captured.value.code == "task_plan_replay_terminal_event_missing"

    recovery = TaskPlanRecoveryService().recover(
        (plan,),
        events_before_terminal,
        results=(result,),
    )
    assert recovery.pending_terminal_results == (result,)
    assert recovery.missing_queue_projections == ()
    assert recovery.awaiting_reclaim == ()
    assert recovery.report.projection.tasks[0].status is TaskLifecycle.RUNNING
    assert worker.calls == 0

    terminal = _lifecycle_event(
        "TASK_COMPLETED",
        7,
        plan,
        instance,
        input_checksum=result.result_checksum,
        output_refs=result.output_refs,
        payload={
            "result_ref": result.result_ref,
            "result_checksum": result.result_checksum,
            "gate_refs": list(result.verified_gate_refs),
            "gate_evidence_refs": list(result.gate_evidence_refs),
        },
    )
    completed = TaskPlanReplayReducer().replay(
        (plan,),
        (*events_before_terminal, terminal),
        results=(result,),
    )
    assert completed.projection.tasks[0].status is TaskLifecycle.SUCCEEDED
    assert completed.projection.tasks[0].result.result_ref == result.result_ref
    assert completed.pending_terminal_results == ()
    assert worker.calls == 0


def test_recovery_quarantines_terminal_failure_without_durable_halt() -> None:
    plan, base_events, worker = _history_fixture()
    instance = task_instance_for_attempt(plan, "recover-task", 1)
    result = replace(
        _result(plan, instance),
        status=TaskLifecycle.FAILED,
        result_ref=None,
        output_refs=(),
        output_roles=(),
        error_code="terminal_failure",
    )
    result_payload = {
        "result_ref": result.result_ref,
        "result_checksum": result.result_checksum,
        "gate_refs": list(result.verified_gate_refs),
        "gate_evidence_refs": list(result.gate_evidence_refs),
    }
    events = (
        *base_events,
        _lifecycle_event("TASK_READY", 3, plan, instance),
        _lifecycle_event("TASK_DISPATCHED", 4, plan, instance),
        _lifecycle_event("TASK_STARTED", 5, plan, instance),
        _lifecycle_event(
            "TASK_RESULT_REJECTED",
            6,
            plan,
            instance,
            output_refs=result.output_refs,
            payload=result_payload,
        ),
        _lifecycle_event(
            "TASK_FAILED",
            7,
            plan,
            instance,
            input_checksum=result.result_checksum,
            output_refs=result.output_refs,
            payload=result_payload,
        ),
    )

    with pytest.raises(HarnessValidationError) as missing_halt:
        TaskPlanRecoveryService().recover((plan,), events, results=(result,))
    assert missing_halt.value.code == "task_plan_recovery_halt_missing"
    assert worker.calls == 0

    halted = TaskPlanEvent(
        "TASK_PLAN_HALTED",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        reason_code="terminal_failure",
        payload={
            "diagnostic_ref": canonical_payload_checksum(
                {"reason_code": "terminal_failure"}
            )
        },
        sequence=8,
    )
    recovery = TaskPlanRecoveryService().recover(
        (plan,),
        (*events, halted),
        results=(result,),
    )
    assert recovery.missing_queue_projections == ()
    assert recovery.awaiting_reclaim == ()
    assert worker.calls == 0


def test_replay_fails_closed_for_missing_result_and_tampered_event_checksum():
    plan, base_events, _ = _history_fixture()
    instance = task_instance_for_attempt(plan, "recover-task", 1)
    result = _result(plan, instance)
    events = (
        *base_events,
        _lifecycle_event("TASK_READY", 3, plan, instance),
        _lifecycle_event("TASK_DISPATCHED", 4, plan, instance),
        _lifecycle_event(
            "TASK_RESULT_ACCEPTED",
            5,
            plan,
            instance,
            output_refs=result.output_refs,
            payload={
                "result_ref": result.result_ref,
                "result_checksum": result.result_checksum,
                "gate_refs": list(result.verified_gate_refs),
                "gate_evidence_refs": list(result.gate_evidence_refs),
            },
        ),
    )
    with pytest.raises(HarnessValidationError) as missing:
        TaskPlanReplayReducer().replay((plan,), events)
    assert missing.value.code == "task_plan_replay_result_missing"

    tampered = replace(events[2])
    object.__setattr__(tampered, "event_checksum", "sha256:" + "0" * 64)
    with pytest.raises(HarnessValidationError) as checksum_error:
        TaskPlanReplayReducer().replay((plan,), (*base_events, tampered))
    assert checksum_error.value.code == "task_plan_replay_event_checksum_mismatch"


def test_replay_requires_patch_document_and_binds_it_to_the_next_plan_version():
    plan, base_events, _ = _history_fixture()
    patch = PlanPatch(
        patch_id="recovery-patch",
        run_id=plan.run_id,
        stage_id=plan.stage_id,
        base_plan_id=plan.plan_id,
        base_plan_version=plan.version,
        reason_code="repair",
        source_candidate_ref="candidate://recovery-patch",
        operations=(
            PlanPatchOperation(
                PlanPatchOperationType.SKIP_PENDING_TASK,
                target_task_id="recover-task",
            ),
        ),
    )
    patched = replace(
        plan,
        plan_id="recovery-plan-v2",
        version=2,
        parent_plan_id=plan.plan_id,
        source_candidate_ref=patch.patch_checksum,
        accepted_at="2026-08-01T00:00:02Z",
    )
    patch_event = TaskPlanEvent(
        "PLAN_PATCH_ACCEPTED",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        input_checksum=patch.patch_checksum,
        reason_code=patch.reason_code,
        payload={"patch_ref": patch.patch_checksum},
        sequence=3,
    )
    plan_event = TaskPlanEvent(
        "PLAN_ACCEPTED",
        run_id=patched.run_id,
        workflow_id=patched.workflow_id,
        stage_id=patched.stage_id,
        graph_checksum=patched.graph_checksum,
        plan_id=patched.plan_id,
        plan_version=patched.version,
        input_checksum=patched.plan_checksum,
        payload={"plan_ref": patched.plan_checksum, "policy_ref": patched.policy_ref},
        sequence=4,
    )
    events = (*base_events, patch_event, plan_event)
    replay = TaskPlanReplayReducer().replay(
        (plan, patched), events, patches=(patch,)
    )
    assert replay.projection.plan_version == 2
    reduced = TaskPlanReplayReducer().reduce(
        (plan, patched),
        events,
        patches=(patch,),
        require_terminal_events=True,
    )
    recovery = TaskPlanRecoveryService().recover(
        (plan, patched),
        events,
        patches=(patch,),
    )
    assert reduced.projection_checksum == replay.projection.projection_checksum
    assert recovery.report.projection.projection_checksum == reduced.projection_checksum
    assert recovery.report.projection.plan_version == 2

    with pytest.raises(HarnessValidationError) as missing:
        TaskPlanReplayReducer().replay((plan, patched), events)
    assert missing.value.code == "task_plan_replay_patch_missing"

    wrong_parent = replace(
        patched,
        parent_plan_id="different-parent",
        source_candidate_ref=patch.patch_checksum,
    )
    with pytest.raises(HarnessValidationError) as mismatch:
        TaskPlanReplayReducer().replay((plan, wrong_parent), events, patches=(patch,))
    assert mismatch.value.code == "task_plan_replay_plan_parent_mismatch"


def test_replay_binds_aggregate_checksum_to_recorded_branch_evidence():
    plan, base_events, _ = _history_fixture()
    output_refs_by_role = {"analysis.result": "result://recover-task"}
    result_refs = ("result://recover-task",)
    branch_refs = (
        {
            "role": "analysis.result",
            "output_ref": "result://recover-task",
            "producer_node_id": "recover-task",
            "output_key": "result",
        },
    )
    aggregate_checksum = canonical_payload_checksum(
        {
            "roles": output_refs_by_role,
            "result_refs": list(result_refs),
            "branch_refs": list(branch_refs),
        }
    )
    aggregate_ref = f"task-plan-aggregate:{aggregate_checksum}"
    aggregate_event = TaskPlanEvent(
        "STAGE_OUTPUT_AGGREGATED",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        input_checksum=aggregate_checksum,
        output_refs=tuple(output_refs_by_role.values()),
        payload={
            "aggregate_ref": aggregate_ref,
            "aggregate_checksum": aggregate_checksum,
            "output_refs_by_role": output_refs_by_role,
            "result_refs": list(result_refs),
            "branch_refs": list(branch_refs),
        },
        sequence=3,
    )
    verified_event = TaskPlanEvent(
        "TASK_PLAN_VERIFIED",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        graph_checksum=plan.graph_checksum,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        input_checksum=aggregate_checksum,
        output_refs=tuple(output_refs_by_role.values()),
        sequence=4,
    )
    report = TaskPlanReplayReducer().replay(
        (plan,), (*base_events, aggregate_event, verified_event)
    )
    assert report.aggregate_checksum == aggregate_checksum

    tampered_payload = dict(aggregate_event.payload)
    tampered_payload["branch_refs"] = [
        {**branch_refs[0], "producer_node_id": "tampered-task"}
    ]
    tampered_event = replace(aggregate_event, payload=tampered_payload)
    with pytest.raises(HarnessValidationError) as mismatch:
        TaskPlanReplayReducer().replay(
            (plan,), (*base_events, tampered_event, verified_event)
        )
    assert mismatch.value.code == "task_plan_replay_aggregate_mismatch"
