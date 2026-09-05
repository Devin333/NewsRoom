from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import canonical_payload_checksum, thaw_mapping
from framework.harness.task_plan.ports import TaskPlanStageRequest
from framework.harness.task_plan.replay import TaskPlanReplayReducer
from framework.harness.task_plan.store import InMemoryTaskPlanStore, TaskResultRecord
from framework.harness.task_plan.submission import CandidateDedupIdentity
from framework.harness.workers.result import HarnessWorkerResult
from tests.framework.harness.agent_loop.test_orchestration_runtime import _runtime, _request
from tests.framework.harness.task_plan.test_durable_task_plan_store import (
    _ArtifactStore, _EventStore, _store,
)


@pytest.fixture(params=["memory", "durable"])
def store_factory(request):
    if request.param == "memory":
        store = InMemoryTaskPlanStore()
        return lambda: store
    events, artifacts = _EventStore(), _ArtifactStore()
    return lambda: _store(events, artifacts)


def _counting_worker(calls):
    def execute(_binding, task, _identity):
        calls.append(task)
        return HarnessWorkerResult(status="succeeded", output={"summary": "completed"})
    return execute


def _submission_identity(request):
    return CandidateDedupIdentity(
        run_id=request.run_id, stage_id="delegate_stage",
        parent_turn_id=request.parent_turn_id,
        action_correlation_id=request.candidate.correlation_id,
    )


def test_terminal_resubmission_reopens_without_new_events_or_worker_calls(store_factory):
    calls = []
    store = store_factory()
    runtime, identity = _runtime(store=store, worker_executor=_counting_worker(calls))
    request = _request(identity)
    first = runtime.dispatch(request)
    assert first.status == "succeeded"
    assert len(calls) == 2
    before = store.read_events(request.run_id, "delegate_stage")
    plan = store.plan(request.run_id, "delegate_stage")

    recovered_store = store_factory()
    recovered, _ = _runtime(store=recovered_store, worker_executor=_counting_worker(calls))
    second = recovered.dispatch(request)

    assert second.to_dict() == first.to_dict()
    assert len(calls) == 2
    assert recovered_store.read_events(request.run_id, "delegate_stage") == before
    assert recovered_store.plan(request.run_id, "delegate_stage") == plan
    assert recovered._stage_runner.parallel_coordinator._sessions == {}


@pytest.mark.parametrize("change", ["objective", "invalid_capability", "parallelism"])
def test_conflicting_candidate_never_receives_old_group_results(store_factory, change):
    calls = []
    store = store_factory()
    runtime, identity = _runtime(store=store, worker_executor=_counting_worker(calls))
    request = _request(identity)
    original = runtime.dispatch(request)
    assert original.status == "succeeded"
    before = store.read_events(request.run_id, "delegate_stage")
    projection = store.load_projection(request.run_id, "delegate_stage")
    candidate = request.candidate
    if change == "parallelism":
        candidate = replace(candidate, parallelism_hint=1)
    else:
        replacement = {"objective": "Changed analysis goal"} if change == "objective" else {"capability_hint": "not-registered"}
        candidate = replace(candidate, tasks=(replace(candidate.tasks[0], **replacement), *candidate.tasks[1:]))
    restarted, _ = _runtime(store=store_factory(), worker_executor=_counting_worker(calls))
    rejected = restarted.dispatch(replace(request, candidate=candidate))

    assert rejected.reason_code == "CANDIDATE_IDEMPOTENCY_CONFLICT"
    assert rejected.status != "succeeded"
    assert rejected.observation.group_id != original.observation.group_id
    assert rejected.observation.result_refs == ()
    assert rejected.observation.task_summaries == ()
    assert rejected.observation.aggregate_ref is None
    assert len(calls) == 2
    assert store.read_events(request.run_id, "delegate_stage") == before
    assert store.load_projection(request.run_id, "delegate_stage") == projection


@pytest.mark.parametrize("field", ["parent_turn_id", "action_correlation_id"])
def test_new_submission_is_not_silently_mapped_to_the_existing_stage(store_factory, field):
    store = store_factory()
    runtime, identity = _runtime(store=store)
    request = _request(identity)
    first = runtime.dispatch(request)
    assert first.status == "succeeded"
    before = store.read_events(request.run_id, "delegate_stage")
    other = (
        replace(request, parent_turn_id="another-parent-turn") if field == "parent_turn_id"
        else replace(request, candidate=replace(request.candidate, correlation_id="another-action"))
    )
    rejected = runtime.dispatch(other)
    assert rejected.reason_code == "task_plan_submission_scope_unavailable"
    assert rejected.observation.aggregate_ref is None
    assert rejected.observation.result_refs == ()
    assert store.read_events(request.run_id, "delegate_stage") == before


def test_restart_between_candidate_commit_and_plan_acceptance_reuses_original_time(store_factory):
    store = store_factory()
    runtime, identity = _runtime(store=store)
    request = _request(identity)
    policy = runtime._policy_registry.resolve(request.policy_ref, stage_id="delegate_stage")
    candidate = runtime._materialize_candidate(request, policy)
    submission = store.admit_candidate_submission(
        candidate, _submission_identity(request), accepted_at="2026-09-05T01:00:00Z",
        candidate_checksum=canonical_payload_checksum(request.candidate.to_dict()),
    )
    restarted_store = store_factory()
    restarted, _ = _runtime(store=restarted_store)
    result = restarted.dispatch(request)

    assert result.status == "succeeded"
    plan = restarted_store.plan(request.run_id, "delegate_stage")
    assert plan.plan_id == submission.plan_id
    assert plan.accepted_at == submission.accepted_at
    events = restarted_store.read_events(request.run_id, "delegate_stage")
    assert sum(item.event_type == "PLAN_CANDIDATE_BUILT" for item in events) == 1
    assert sum(item.event_type == "PLAN_ACCEPTED" for item in events) == 1


def test_restart_with_no_candidate_reads_durable_candidate_without_calling_builder(store_factory):
    store = store_factory()
    runtime, identity = _runtime(store=store)
    parent_request = _request(identity)
    policy = runtime._policy_registry.resolve(parent_request.policy_ref, stage_id="delegate_stage")
    candidate = runtime._materialize_candidate(parent_request, policy)
    submission = store.admit_candidate_submission(
        candidate, _submission_identity(parent_request), accepted_at="2026-09-05T01:00:00Z",
        candidate_checksum=canonical_payload_checksum(parent_request.candidate.to_dict()),
    )
    recovered, _ = _runtime(store=store_factory())
    result = recovered._stage_runner.run(TaskPlanStageRequest(
        run_id=identity.run_id, stage_binding=runtime._stage_binding, context_refs={"document": "document"},
        policy=policy, accepted_at="2026-09-05T02:00:00Z",
        submission_identity=submission.identity,
        execution_identity=runtime._task_plan_execution_identity(identity, parent_request.candidate),
    ))
    assert result.status.value == "succeeded"
    assert recovered._store.plan(identity.run_id, "delegate_stage").accepted_at == submission.accepted_at


class _RejectingVerifier:
    registered_gate_refs = ("gate@1",)

    def verify(self, _result, *, task, request):
        instance = request.instance
        return TaskResultRecord.for_plan(
            request.plan, task_id=instance.task_id,
            task_instance_id=instance.task_instance_id, attempt=instance.attempt,
            status="failed", error_code="gate_failed",
        )


def test_terminal_failure_reuses_original_observation_without_new_attempts(store_factory):
    calls = []
    store = store_factory()
    runtime, identity = _runtime(
        store=store, worker_executor=_counting_worker(calls), result_verifier=_RejectingVerifier(),
    )
    request = _request(identity)
    failed = runtime.dispatch(request)
    assert failed.status == "partial_failure"
    count = len(calls)
    assert count == 2
    before = store.read_events(request.run_id, "delegate_stage")
    recovered, _ = _runtime(store=store_factory(), worker_executor=_counting_worker(calls))
    repeated = recovered.dispatch(request)
    assert repeated.to_dict() == failed.to_dict()
    assert len(calls) == count
    assert store.read_events(request.run_id, "delegate_stage") == before


@pytest.mark.parametrize("field", [
    "aggregate_ref", "submission_key", "checksum", "accepted_at", "missing_outcome",
    "late_candidate", "diagnostics",
])
def test_replay_rejects_tampered_submission_outcome_without_live_calls(field):
    store = InMemoryTaskPlanStore()
    calls = []
    runtime, identity = _runtime(store=store, worker_executor=_counting_worker(calls))
    request = _request(identity)
    assert runtime.dispatch(request).status == "succeeded"
    events = list(store.read_events(identity.run_id, "delegate_stage"))
    plan = store.plan(identity.run_id, "delegate_stage")
    if field == "accepted_at":
        plans = (replace(plan, accepted_at="2026-01-01T00:00:00Z"),)
        accepted_index = next(i for i, e in enumerate(events) if e.event_type == "PLAN_ACCEPTED")
        accepted = events[accepted_index]
        events[accepted_index] = replace(accepted, input_checksum=plans[0].plan_checksum,
                                         payload={**thaw_mapping(accepted.payload), "plan_ref": plans[0].plan_checksum})
    elif field == "late_candidate":
        plans = (plan,)
        candidate = events.pop(0)
        assert candidate.event_type == "PLAN_CANDIDATE_BUILT"
        events.insert(1, candidate)
        events = [replace(event, sequence=i + 1) for i, event in enumerate(events)]
    else:
        plans = (plan,)
        event = events[-1]
        assert event.event_type == "TASK_PLAN_VERIFIED"
        payload = thaw_mapping(event.payload)
        if field == "aggregate_ref":
            payload["terminal_result"]["output"]["aggregate_ref"] = "artifact://forged-output"
            payload["terminal_result_checksum"] = HarnessWorkerResult.from_dict(payload["terminal_result"]).candidate_result_ref
        elif field == "submission_key":
            payload["submission_key"] = canonical_payload_checksum({"another": "submission"})
        elif field == "diagnostics":
            payload["terminal_result"]["diagnostics"]["plan_id"] = "another-plan"
            payload["terminal_result_checksum"] = HarnessWorkerResult.from_dict(payload["terminal_result"]).candidate_result_ref
        elif field == "missing_outcome":
            for key in ("submission_key", "terminal_result", "terminal_result_checksum"):
                del payload[key]
        else:
            payload["terminal_result_checksum"] = canonical_payload_checksum({"wrong": "checksum"})
        events[-1] = replace(event, payload=payload)
    with pytest.raises(HarnessValidationError) as rejected:
        TaskPlanReplayReducer().replay(
            plans, events, results=store.result_history_for(plan.run_id, plan.stage_id, plan.plan_id, plan.version),
        )
    assert rejected.value.code in {"task_plan_submission_result_invalid", "task_plan_replay_candidate_mismatch"}
    assert len(calls) == 2


def test_stage_rejects_changed_candidate_without_submission_identity():
    store = InMemoryTaskPlanStore()
    runtime, identity = _runtime(store=store)
    request = _request(identity)
    policy = runtime._policy_registry.resolve(request.policy_ref, stage_id="delegate_stage")
    candidate = runtime._materialize_candidate(request, policy)
    stage_request = TaskPlanStageRequest(
        run_id=identity.run_id, stage_binding=runtime._stage_binding,
        context_refs={"document": "document"}, policy=policy,
        accepted_at="2026-09-05T00:00:00Z", candidate=candidate,
        execution_identity=runtime._task_plan_execution_identity(identity, request.candidate),
    )
    assert runtime._stage_runner.run(stage_request).status.value == "succeeded"
    before = store.read_events(identity.run_id, "delegate_stage")
    changed = replace(candidate, tasks=(replace(candidate.tasks[0], objective="Changed goal"), *candidate.tasks[1:]))
    rejected = runtime._stage_runner.run(replace(stage_request, candidate=changed))
    assert rejected.diagnostics["reason_code"] == "task_plan_candidate_conflict"
    assert rejected.output == {}
    assert store.read_events(identity.run_id, "delegate_stage") == before


def test_corrupt_terminal_cache_fails_closed_without_reexecuting_workers():
    store = InMemoryTaskPlanStore()
    calls = []
    runtime, identity = _runtime(store=store, worker_executor=_counting_worker(calls))
    request = _request(identity)
    assert runtime.dispatch(request).status == "succeeded"
    events = store._events[(identity.run_id, "delegate_stage")]
    terminal = events[-1]
    payload = thaw_mapping(terminal.payload)
    del payload["submission_key"]
    events[-1] = replace(terminal, payload=payload)
    before = tuple(events)
    restarted, _ = _runtime(store=store, worker_executor=_counting_worker(calls))
    result = restarted.dispatch(request)
    assert result.reason_code == "task_plan_submission_result_invalid"
    assert result.observation.result_refs == ()
    assert result.observation.aggregate_ref is None
    assert len(calls) == 2
    assert tuple(events) == before
