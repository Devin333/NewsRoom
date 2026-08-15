from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from framework.agent.artifacts import FilesystemArtifactStore
from framework.events.runtime.publisher import EventRuntime
from framework.events.schema import default_event_schema_catalog
from framework.harness import (
    ContextEnvelope,
    DurableTaskPlanStore,
    FakePlanCandidateBuilder,
    HarnessBudget,
    HarnessBudgetSnapshot,
    HarnessValidationError,
    HarnessWorkerResult,
    InMemoryTaskPlanStore,
    PlanBuildBudget,
    PlanCandidate,
    ResolvedSubAgentTaskAdapter,
    SubAgentRuntime,
    SubAgentSpec,
    SubAgentStatus,
    TaskAcceptanceCriteria,
    TaskBudget,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
    TaskLifecycle,
    TaskOutputContract,
    TaskPlanEvent,
    TaskPlanGateRegistry,
    TaskPlanPolicy,
    TaskPlanReadyDecision,
    TaskPlanReplayReducer,
    TaskPlanResultVerifier,
    TaskPlanScheduler,
    TaskPlanStageRequest,
    TaskPlanStageRunner,
    TaskPlanValidationContext,
    TaskPlanValidator,
    TaskResultRecord,
    TaskRetryPolicy,
    TaskSpec,
    canonical_payload_checksum,
    subagent_attempt_evidence,
    task_instance_for_attempt,
)
from framework.harness.task_plan.store import TASK_PLAN_RESULT_SCHEMA_V1
from framework.harness.graph import HarnessWorkerType
from framework.harness.graph.bindings import HarnessWorkerBinding
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from infrastructure.storage.harness import FilesystemSubAgentTranscriptStore
from infrastructure.storage.events import SQLiteEventStore
from tests.fixtures.task_plan import build_task_plan_stage_binding


ACCEPTED_AT = "2026-08-13T00:00:00Z"


class _CountingSubAgentWorker:
    worker_id = "lineage-subagent"
    worker_version = "1"
    worker_type = HarnessWorkerType.SUBAGENT

    def __init__(
        self,
        *,
        status: str = "succeeded",
        artifacts: tuple[str, ...] = (),
    ) -> None:
        self.status = status
        self.artifacts = artifacts
        self.calls = 0

    def execute(self, _task):
        self.calls += 1
        return HarnessWorkerResult(
            status=self.status,
            output={"result": "durable candidate"},
            artifacts=self.artifacts,
            error=None if self.status == "succeeded" else "worker failed",
        )


class _RecordingArtifactVerifier:
    def __init__(self, valid_refs: tuple[str, ...] = ()) -> None:
        self.valid_refs = set(valid_refs)
        self.calls: list[tuple[str, str]] = []

    def verify_artifact_ref(self, ref: str, *, expected_run_id: str) -> None:
        self.calls.append((ref, expected_run_id))
        if expected_run_id != "lineage-run" or ref not in self.valid_refs:
            raise ValueError("artifact evidence is not owned by the accepted run")


def _fixture(
    tmp_path: Path,
    *,
    worker_status: str = "succeeded",
    worker_artifacts: tuple[str, ...] = (),
    artifact_reference_verifier=None,
):
    spec = SubAgentSpec(
        subagent_id="lineage-subagent",
        role="analysis.lineage",
        purpose="Produce one durable candidate for TaskPlan lineage tests.",
        input_schema={
            "required": ["input_refs", "task_id", "task_definition_checksum"],
        },
        output_schema={
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        allowed_tools=("research.read",),
        allowed_memory_namespaces=("research.public",),
        context_policy={"allow_sibling_history": False},
        budget={"max_turns": 2, "max_tool_calls": 1, "max_memory_ops": 1},
    )
    worker = _CountingSubAgentWorker(
        status=worker_status,
        artifacts=worker_artifacts,
    )
    registration = TaskCapabilityRegistration(
        capability="research.lineage",
        worker_binding=HarnessWorkerBinding(
            HarnessContractReference(
                HarnessContractKind.WORKER,
                worker.worker_id,
                worker.worker_version,
            ),
            HarnessWorkerType.SUBAGENT,
            worker,
        ),
        worker_contract_ref="lineage-worker-contract@1",
        input_schema_ref="lineage-input@1",
        output_schema_ref="lineage-output@1",
        subagent_spec=spec,
    )
    registry = TaskCapabilityRegistry((registration,))
    policy = TaskPlanPolicy(
        policy_id="lineage.task-plan",
        version="1",
        stage_id="dynamic_stage",
        allowed_worker_capabilities=("research.lineage",),
        allowed_subagent_ids=(spec.subagent_id,),
        allowed_tool_ids=("research.read",),
        allowed_memory_namespaces=("research.public",),
        allowed_input_refs=("document",),
        allowed_output_roles=("analysis.lineage",),
        required_output_roles=("analysis.lineage",),
        allowed_output_schema_refs=("lineage-output@1",),
        allowed_gate_refs=("LineageGate@1",),
        deterministic_aggregator_refs={},
        pinned_capability_bindings={
            "research.lineage": registration.worker_ref,
        },
        required_worker_contract_refs={
            "research.lineage": registration.worker_contract_ref,
        },
        max_tasks=2,
        max_depth=2,
        max_parallelism=1,
        max_replans=0,
        max_task_attempts=1,
        max_plan_build_calls=1,
        max_plan_build_turns=1,
        max_plan_build_tool_calls=0,
        per_task_budget=TaskBudget(
            max_turns=2,
            max_tool_calls=1,
            max_memory_ops=1,
            max_output_tokens=128,
        ),
        aggregate_task_budget=TaskBudget(
            max_turns=2,
            max_tool_calls=1,
            max_memory_ops=1,
            max_output_tokens=128,
        ),
    )
    stage_binding = build_task_plan_stage_binding(
        workflow_id="lineage-workflow",
        stage_id=policy.stage_id,
        policy_ref=policy.exact_ref,
        required_output_roles=policy.required_output_roles,
        input_keys=("document",),
    )
    task = TaskSpec(
        task_id="lineage-task",
        objective="Verify durable subagent lineage.",
        worker_capability="research.lineage",
        input_refs=("document",),
        output_contract=TaskOutputContract(
            "lineage-output@1",
            "analysis.lineage",
        ),
        acceptance_criteria=TaskAcceptanceCriteria(("LineageGate@1",)),
        requested_tools=("research.read",),
        requested_memory_namespaces=("research.public",),
        budget_request=policy.per_task_budget,
        retry_policy=TaskRetryPolicy(max_attempts=1),
    )
    candidate = PlanCandidate(
        candidate_id="lineage-candidate",
        run_id="lineage-run",
        workflow_id="lineage-workflow",
        stage_id="dynamic_stage",
        graph_checksum=stage_binding.graph_checksum,
        input_context_refs=("document",),
        tasks=(task,),
        required_output_roles=("analysis.lineage",),
        generated_by="lineage-planner@1",
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
        accepted_at=ACCEPTED_AT,
    )
    transcript_store = FilesystemSubAgentTranscriptStore(tmp_path / "artifacts")
    runtime = SubAgentRuntime(
        workers={spec.subagent_id: worker},
        transcript_store=transcript_store,
    )
    adapter = ResolvedSubAgentTaskAdapter(runtime)
    gates = TaskPlanGateRegistry()
    gates.register("LineageGate@1", lambda _request: True, deterministic=True)
    verifier = TaskPlanResultVerifier(
        gates,
        transcript_store=transcript_store,
        artifact_reference_verifier=artifact_reference_verifier,
    )
    context_pack = ContextEnvelope(
        envelope_id="lineage-context",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        step_id=plan.stage_id,
        phase="EXECUTE",
        worker_id="lineage-task-plan",
        worker_type=HarnessWorkerType.TASK_PLAN.value,
        dynamic_tail={"input_refs": ["document"]},
    )
    budget = HarnessBudgetSnapshot.from_budget(HarnessBudget.safe_default())
    binding = registry.resolve(task.worker_capability, policy)
    resolved = plan.tasks[0]
    instance = task_instance_for_attempt(plan, task.task_id, 1)

    def invoke():
        child = adapter.invoke(
            resolved_task=resolved,
            binding=binding,
            task_instance_id=instance.task_instance_id,
            parent_run_id=plan.run_id,
            workflow_id=plan.workflow_id,
            stage_id=plan.stage_id,
            context_pack=context_pack,
            budget_snapshot=budget,
            attempt=instance.attempt,
            observed_at=plan.accepted_at,
        )
        return _worker_result_from_child(child)

    def recover(_binding, active_instance):
        assert active_instance == instance
        child = adapter.recover(
            resolved_task=resolved,
            binding=binding,
            task_instance_id=instance.task_instance_id,
            parent_run_id=plan.run_id,
            workflow_id=plan.workflow_id,
            stage_id=plan.stage_id,
            context_pack=context_pack,
            budget_snapshot=budget,
            attempt=instance.attempt,
            observed_at=plan.accepted_at,
        )
        return None if child is None else _worker_result_from_child(child, recovered=True)

    request = TaskPlanStageRequest(
        run_id=plan.run_id,
        stage_binding=stage_binding,
        context_refs={"document": "document"},
        policy=policy,
        policy_ref=policy.exact_ref,
        accepted_at=ACCEPTED_AT,
        candidate=candidate,
    )
    return {
        "candidate": candidate,
        "plan": plan,
        "policy": policy,
        "registry": registry,
        "worker": worker,
        "transcript_store": transcript_store,
        "artifact_reference_verifier": artifact_reference_verifier,
        "verifier": verifier,
        "instance": instance,
        "resolved": resolved,
        "invoke": invoke,
        "recover": recover,
        "request": request,
    }


def _worker_result_from_child(child, *, recovered: bool = False) -> HarnessWorkerResult:
    succeeded = child.status is SubAgentStatus.SUCCEEDED
    return HarnessWorkerResult(
        status="succeeded" if succeeded else "failed",
        output=child.output,
        artifacts=child.artifact_refs,
        diagnostics={"subagent_id": child.subagent_id, "recovered": recovered},
        evidence=(subagent_attempt_evidence(child.transcript_receipt),)
        if child.transcript_receipt is not None
        else (),
        error=None if succeeded else "subagent attempt failed",
    )


def _start_attempt(store, plan, instance) -> None:
    scheduler = TaskPlanScheduler()
    projection = scheduler.reserve_ready_tasks(
        store.load_projection(plan.run_id, plan.stage_id),
        TaskPlanReadyDecision((instance,)),
    )
    transitions = (
        ("TASK_READY", lambda value: value),
        ("TASK_DISPATCHED", lambda value: scheduler.mark_dispatched(value, instance)),
        ("TASK_STARTED", lambda value: scheduler.mark_started(value, instance)),
    )
    for event_type, transition in transitions:
        projection = transition(projection)
        sequence = len(store.read_events(plan.run_id, plan.stage_id)) + 1
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


def _committed_lineage(
    tmp_path: Path,
    *,
    worker_status: str = "succeeded",
    worker_artifacts: tuple[str, ...] = (),
    artifact_reference_verifier=None,
):
    fixture = _fixture(
        tmp_path,
        worker_status=worker_status,
        worker_artifacts=worker_artifacts,
        artifact_reference_verifier=artifact_reference_verifier,
    )
    store = InMemoryTaskPlanStore()
    store.append_candidate(fixture["candidate"])
    store.accept_plan(fixture["plan"])
    _start_attempt(store, fixture["plan"], fixture["instance"])
    worker_result = fixture["invoke"]()
    record = fixture["verifier"].verify(
        worker_result,
        task=fixture["resolved"],
        request=fixture["instance"],
        workflow_id=fixture["plan"].workflow_id,
    )
    store.append_result(record)
    fixture.update(store=store, worker_result=worker_result, record=record)
    return fixture


def test_success_and_failure_events_carry_complete_typed_lineage(tmp_path: Path) -> None:
    succeeded = _committed_lineage(tmp_path / "succeeded")
    failed = _committed_lineage(tmp_path / "failed", worker_status="failed")

    for fixture, result_event_type, terminal_event_type in (
        (succeeded, "TASK_RESULT_ACCEPTED", "TASK_COMPLETED"),
        (failed, "TASK_RESULT_REJECTED", "TASK_FAILED"),
    ):
        record = fixture["record"]
        assert record.transcript_ref is not None
        assert record.transcript_checksum is not None
        assert record.subagent_output_ref is not None
        assert record.subagent_output_checksum is not None
        if record.status is TaskLifecycle.SUCCEEDED:
            assert record.result_ref == record.subagent_output_ref
        else:
            assert record.result_ref is None
        events = fixture["store"].read_events(
            fixture["plan"].run_id,
            fixture["plan"].stage_id,
        )
        result_event = next(item for item in events if item.event_type == result_event_type)
        terminal_event = next(item for item in events if item.event_type == terminal_event_type)
        for event in (result_event, terminal_event):
            assert event.payload["transcript_ref"] == record.transcript_ref
            assert event.payload["transcript_checksum"] == record.transcript_checksum
            assert event.payload["subagent_output_ref"] == record.subagent_output_ref
            assert event.payload["subagent_output_checksum"] == record.subagent_output_checksum
        transcript = fixture["transcript_store"].read(record.transcript_ref)
        output = fixture["transcript_store"].read_output(record.subagent_output_ref)
        assert transcript.identity.task_instance_id == record.task_instance_id
        assert transcript.identity.attempt == record.attempt
        assert output.output_checksum == record.subagent_output_checksum


def test_offline_replay_verifies_transcript_and_rejects_event_lineage_mismatch(
    tmp_path: Path,
) -> None:
    fixture = _committed_lineage(tmp_path)
    events = fixture["store"].read_events(
        fixture["plan"].run_id,
        fixture["plan"].stage_id,
    )
    worker_calls = fixture["worker"].calls

    report = TaskPlanReplayReducer(fixture["transcript_store"]).replay(
        (fixture["plan"],),
        events,
        results=(fixture["record"],),
    )

    assert report.projection.tasks[0].status is TaskLifecycle.SUCCEEDED
    assert report.accepted_output_refs == (fixture["record"].subagent_output_ref,)
    assert fixture["worker"].calls == worker_calls == 1

    result_event_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "TASK_RESULT_ACCEPTED"
    )
    payload = dict(events[result_event_index].payload)
    payload["subagent_output_checksum"] = "sha256:" + "f" * 64
    tampered_events = list(events)
    tampered_events[result_event_index] = replace(
        events[result_event_index],
        payload=payload,
    )
    with pytest.raises(HarnessValidationError) as captured:
        TaskPlanReplayReducer(fixture["transcript_store"]).replay(
            (fixture["plan"],),
            tuple(tampered_events),
            results=(fixture["record"],),
        )
    assert captured.value.code == "task_plan_replay_result_mismatch"
    assert fixture["worker"].calls == worker_calls


def test_subagent_artifact_refs_require_the_canonical_owner(tmp_path: Path) -> None:
    artifact_ref = "artifact://lineage-run/candidate"
    missing = _fixture(
        tmp_path / "missing-verifier",
        worker_artifacts=(artifact_ref,),
    )
    with pytest.raises(HarnessValidationError) as missing_error:
        missing["verifier"].verify(
            missing["invoke"](),
            task=missing["resolved"],
            request=missing["instance"],
            workflow_id=missing["plan"].workflow_id,
        )
    assert missing_error.value.code == "task_plan_subagent_artifact_verifier_required"

    rejecting_verifier = _RecordingArtifactVerifier()
    fabricated = _fixture(
        tmp_path / "fabricated",
        worker_artifacts=(artifact_ref,),
        artifact_reference_verifier=rejecting_verifier,
    )
    with pytest.raises(HarnessValidationError) as fabricated_error:
        fabricated["verifier"].verify(
            fabricated["invoke"](),
            task=fabricated["resolved"],
            request=fabricated["instance"],
            workflow_id=fabricated["plan"].workflow_id,
        )
    assert fabricated_error.value.code == "task_plan_subagent_artifact_unverified"
    assert fabricated_error.value.details == {"artifact_index": 0}

    accepting_verifier = _RecordingArtifactVerifier((artifact_ref,))
    accepted = _committed_lineage(
        tmp_path / "accepted",
        worker_artifacts=(artifact_ref,),
        artifact_reference_verifier=accepting_verifier,
    )
    assert accepted["record"].output_refs == (artifact_ref,)
    assert accepting_verifier.calls == [(artifact_ref, "lineage-run")]


def test_offline_replay_revalidates_artifact_refs_without_live_worker_call(
    tmp_path: Path,
) -> None:
    artifact_ref = "artifact://lineage-run/candidate"
    artifact_verifier = _RecordingArtifactVerifier((artifact_ref,))
    fixture = _committed_lineage(
        tmp_path,
        worker_artifacts=(artifact_ref,),
        artifact_reference_verifier=artifact_verifier,
    )
    events = fixture["store"].read_events(
        fixture["plan"].run_id,
        fixture["plan"].stage_id,
    )
    worker_calls = fixture["worker"].calls

    replay = TaskPlanReplayReducer(
        fixture["transcript_store"],
        artifact_reference_verifier=artifact_verifier,
    ).replay(
        (fixture["plan"],),
        events,
        results=(fixture["record"],),
    )

    assert replay.verified is True
    assert fixture["worker"].calls == worker_calls == 1
    assert artifact_verifier.calls == [
        (artifact_ref, "lineage-run"),
        (artifact_ref, "lineage-run"),
    ]

    artifact_verifier.valid_refs.clear()
    with pytest.raises(HarnessValidationError) as changed_error:
        TaskPlanReplayReducer(
            fixture["transcript_store"],
            artifact_reference_verifier=artifact_verifier,
        ).replay(
            (fixture["plan"],),
            events,
            results=(fixture["record"],),
        )
    assert changed_error.value.code == "task_plan_subagent_artifact_unverified"
    assert fixture["worker"].calls == worker_calls

    with pytest.raises(HarnessValidationError) as missing_error:
        TaskPlanReplayReducer(fixture["transcript_store"]).replay(
            (fixture["plan"],),
            events,
            results=(fixture["record"],),
        )
    assert missing_error.value.code == "task_plan_subagent_artifact_verifier_required"


def test_artifact_verification_failure_halts_parent_without_task_result(
    tmp_path: Path,
) -> None:
    artifact_ref = "artifact://lineage-run/fabricated"
    artifact_verifier = _RecordingArtifactVerifier()
    fixture = _fixture(
        tmp_path,
        worker_artifacts=(artifact_ref,),
        artifact_reference_verifier=artifact_verifier,
    )
    database = tmp_path / "task-plan-events.sqlite3"
    # Keep immutable TaskPlan document paths below the Windows legacy path limit.
    task_plan_artifacts = tmp_path.parent / "halt-artifacts"
    event_store = SQLiteEventStore(database)
    store = DurableTaskPlanStore(
        EventRuntime(
            store=event_store,
            schema_catalog=default_event_schema_catalog(),
        ),
        event_store,
        artifact_store=FilesystemArtifactStore(task_plan_artifacts),
    )
    runner = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(fixture["candidate"]),
        capability_registry=fixture["registry"],
        store=store,
        result_verifier=fixture["verifier"],
        worker_executor=lambda *_args: fixture["invoke"](),
    )

    result = runner.run(fixture["request"])

    assert result.status.value == "blocked"
    assert result.diagnostics["reason_code"] == "task_plan_subagent_artifact_unverified"
    reopened_event_store = SQLiteEventStore(database)
    reopened = DurableTaskPlanStore(
        EventRuntime(
            store=reopened_event_store,
            schema_catalog=default_event_schema_catalog(),
        ),
        reopened_event_store,
        artifact_store=FilesystemArtifactStore(task_plan_artifacts),
    )
    plan = reopened.plan(fixture["plan"].run_id, fixture["plan"].stage_id)
    assert plan is not None
    assert reopened.results_for(
        plan.run_id,
        plan.stage_id,
        plan.plan_id,
        plan.version,
    ) == ()
    events = reopened.read_events(plan.run_id, plan.stage_id)
    assert events[-1].event_type == "TASK_PLAN_HALTED"
    assert events[-1].reason_code == "task_plan_subagent_artifact_unverified"
    assert not {
        "TASK_RESULT_ACCEPTED",
        "TASK_RESULT_REJECTED",
        "TASK_COMPLETED",
        "TASK_FAILED",
    }.intersection(event.event_type for event in events)


def test_receipt_before_task_result_is_recovered_without_live_worker_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    store = InMemoryTaskPlanStore()
    store.append_candidate(fixture["candidate"])
    store.accept_plan(fixture["plan"])
    _start_attempt(store, fixture["plan"], fixture["instance"])

    first = fixture["invoke"]()
    assert len(first.evidence) == 1
    assert fixture["worker"].calls == 1
    assert store.results_for(
        fixture["plan"].run_id,
        fixture["plan"].stage_id,
        fixture["plan"].plan_id,
        fixture["plan"].version,
    ) == ()

    runner = TaskPlanStageRunner(
        candidate_builder=FakePlanCandidateBuilder(fixture["candidate"]),
        capability_registry=fixture["registry"],
        store=store,
        result_verifier=fixture["verifier"],
        worker_executor=lambda *_args: pytest.fail("live worker must not be called"),
        worker_result_recovery=fixture["recover"],
    )
    result = runner.run(fixture["request"])

    assert result.status.value == "succeeded"
    assert fixture["worker"].calls == 1
    records = store.results_for(
        fixture["plan"].run_id,
        fixture["plan"].stage_id,
        fixture["plan"].plan_id,
        fixture["plan"].version,
    )
    assert len(records) == 1
    assert records[0].transcript_ref == first.evidence[0].payload["transcript_ref"]
    event_types = [
        event.event_type
        for event in store.read_events(
            fixture["plan"].run_id,
            fixture["plan"].stage_id,
        )
    ]
    assert event_types[-4:] == [
        "TASK_RESULT_ACCEPTED",
        "TASK_COMPLETED",
        "STAGE_OUTPUT_AGGREGATED",
        "TASK_PLAN_VERIFIED",
    ]


def test_unversioned_v1_result_roundtrips_but_subagent_replay_is_unavailable(
    tmp_path: Path,
) -> None:
    fixture = _committed_lineage(tmp_path)
    record = fixture["record"]
    legacy = TaskResultRecord(
        run_id=record.run_id,
        workflow_id=record.workflow_id,
        stage_id=record.stage_id,
        plan_id=record.plan_id,
        plan_version=record.plan_version,
        task_id=record.task_id,
        task_instance_id=record.task_instance_id,
        attempt=record.attempt,
        worker_ref=record.worker_ref,
        task_checksum=record.task_checksum,
        binding_checksum=record.binding_checksum,
        status=record.status,
        result_ref="result://legacy-subagent",
        output_refs=record.output_refs,
        output_roles=record.output_roles,
        output_schema_ref=record.output_schema_ref,
        usage=record.usage,
        verified_gate_refs=record.verified_gate_refs,
        gate_evidence_refs=record.gate_evidence_refs,
        schema_version=TASK_PLAN_RESULT_SCHEMA_V1,
    )
    restored = TaskResultRecord.from_dict(legacy.to_dict())

    assert restored.schema_version == TASK_PLAN_RESULT_SCHEMA_V1
    assert "schema_version" not in legacy.to_dict()
    assert restored.transcript_ref is None

    events = fixture["store"].read_events(
        fixture["plan"].run_id,
        fixture["plan"].stage_id,
    )
    legacy_events = []
    for event in events:
        if event.event_type not in {"TASK_RESULT_ACCEPTED", "TASK_COMPLETED"}:
            legacy_events.append(event)
            continue
        payload = dict(event.payload)
        payload.update(
            {
                "result_ref": legacy.result_ref,
                "result_checksum": legacy.result_checksum,
                "transcript_ref": None,
                "transcript_checksum": None,
                "subagent_output_ref": None,
                "subagent_output_checksum": None,
            }
        )
        legacy_events.append(
            replace(
                event,
                input_checksum=(
                    legacy.result_checksum
                    if event.event_type == "TASK_COMPLETED"
                    else legacy.task_checksum
                ),
                payload=payload,
            )
        )
    with pytest.raises(HarnessValidationError) as captured:
        TaskPlanReplayReducer(fixture["transcript_store"]).replay(
            (fixture["plan"],),
            tuple(legacy_events),
            results=(legacy,),
        )
    assert captured.value.code == "subagent_transcript_legacy_unavailable"


def test_non_subagent_v1_result_remains_readable() -> None:
    legacy = TaskResultRecord(
        run_id="legacy-run",
        workflow_id="legacy-workflow",
        stage_id="legacy-stage",
        plan_id="legacy-plan",
        plan_version=1,
        task_id="legacy-task",
        task_instance_id="legacy-instance",
        attempt=1,
        worker_ref="legacy-worker@1",
        task_checksum="sha256:" + "1" * 64,
        binding_checksum="sha256:" + "2" * 64,
        status=TaskLifecycle.SUCCEEDED,
        result_ref="result://legacy",
        output_refs=("artifact://legacy",),
        output_roles=("analysis.legacy",),
        output_schema_ref="legacy-output@1",
        schema_version=TASK_PLAN_RESULT_SCHEMA_V1,
    )

    assert TaskResultRecord.from_dict(legacy.to_dict()) == legacy
