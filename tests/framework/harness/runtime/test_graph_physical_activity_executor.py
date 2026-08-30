from __future__ import annotations

from datetime import UTC, datetime
import threading
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.graph_application import (
    HarnessGraphActivityCancellationRequest,
    HarnessGraphActivityDispatcherPort,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResultStatus,
)
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    HarnessAdmittedGraphActivityAttempt,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputResourceIdentity,
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    HarnessWorkerType,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessActivityUsage,
    HarnessLeafActivityBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


from framework.harness.control_plane.activity_execution import (
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA,
    HarnessGraphActivityExecutionInput,
    HarnessGraphActivityTaskContext,
)
from framework.harness.runtime.activity_executor import (
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.runtime.graph_dispatcher import (
    HarnessGraphPhysicalActivityDispatcher,
)
from backend.research.graphs import build_paper_analysis_graph_definition
from framework.harness.graph import HarnessGraphCompiler, graph_activity_input_checksum
from framework.harness.runtime.node_output import (
    HarnessAdmittedGraphActivityOutputAdapter,
)
from framework.harness.workers.result import (
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.shared.attempts import (
    AttemptContext,
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    current_attempt_context,
)


_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
_WORKER_REF = HarnessContractReference(
    HarnessContractKind.WORKER,
    "test.graph-candidate-worker",
    "1",
)
_ACTIVITY_REF = HarnessContractReference(
    HarnessContractKind.ACTIVITY,
    "test.graph-candidate-activity",
    "1",
)
_CHECKPOINT_REF = "checkpoint://run-1/decision-3"


class _ActivityContract:
    activity_contract_id = _ACTIVITY_REF.contract_id
    activity_contract_version = _ACTIVITY_REF.version

    def __init__(self, *, capabilities: HarnessActivityCapabilities) -> None:
        self.capabilities = capabilities
        self.dispatch_calls = 0

    def dispatch(self, _request: object) -> None:
        self.dispatch_calls += 1
        raise AssertionError("physical executor must not call the legacy dispatch shape")


class _Worker:
    worker_id = _WORKER_REF.contract_id
    worker_version = _WORKER_REF.version
    worker_type = HarnessWorkerType.FUNCTION

    def __init__(self, fn=None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fn = fn or (
            lambda _task: HarnessWorkerResult(
                status=HarnessWorkerStatus.SUCCEEDED,
                output={"report": {"value": "candidate"}},
            )
        )

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        self.calls.append(task)
        return self._fn(task)


class _InputResolver:
    def __init__(self, value: HarnessGraphActivityExecutionInput) -> None:
        self.value = value
        self.calls: list[HarnessGraphActivity] = []

    def resolve_execution_input(
        self,
        activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        self.calls.append(activity)
        return self.value


class _ResultCommitter:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls: list[dict[str, Any]] = []
        self.results = {}

    def commit_execution_result(self, **values):
        self.calls.append(values)
        if self.fail_once:
            self.fail_once = False
            raise OSError("result store unavailable")
        result = values["result"]
        existing = self.results.get(result.activity_id)
        if existing is not None and existing != result:
            raise HarnessValidationError(
                "conflicting activity result",
                code="test_graph_activity_result_conflict",
            )
        self.results[result.activity_id] = result
        return result


def test_executor_uses_exact_graph_pair_and_commits_activity_bound_output() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    activity_contract = _ActivityContract(
        capabilities=HarnessActivityCapabilities(stable_idempotency=True)
    )
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    execution_input = _execution_input(activity, task)
    executor = _executor(
        execution_input=execution_input,
        worker=worker,
        activity_contract=activity_contract,
        resource=resource,
        committer=committer,
    )

    receipt = executor.execute(activity, attempt_id="physical-attempt-1")

    assert isinstance(executor, HarnessGraphActivityDispatcherPort)
    assert receipt.attempt is not None
    assert receipt.attempt.outcome.state is AttemptState.SUCCEEDED
    assert receipt.node_output_commit is not None
    assert receipt.node_output_commit.candidate.output_refs == {
        "report": checksum_for({"report": {"value": "candidate"}})
    }
    assert receipt.worker_result is not None
    assert receipt.worker_result.candidate_result_ref in (
        receipt.node_output_commit.candidate.evidence_refs
    )
    assert receipt.graph_result is not None
    assert receipt.graph_result.status is HarnessGraphActivityResultStatus.SUCCEEDED
    assert receipt.graph_result.activity_id == activity.activity_id
    assert receipt.graph_result.evidence_ref == receipt.node_output_commit.commit_ref
    assert (
        receipt.graph_result.payload_ref
        == receipt.node_output_commit.candidate.candidate_ref
    )
    assert resource.committed_output(
        HarnessNodeOutputResourceIdentity.for_activity(activity)
    ) == receipt.node_output_commit
    assert len(committer.calls) == 1
    assert committer.calls[0]["worker_result"] == receipt.worker_result
    assert activity_contract.dispatch_calls == 0
    assert len(worker.calls) == 1
    assert "harness_activity" not in worker.calls[0]
    task_context = HarnessGraphActivityTaskContext.from_dict(
        worker.calls[0][HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY]
    )
    assert task_context.schema_version == HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_SCHEMA
    assert task_context.activity == activity
    assert task_context.graph_checkpoint_ref == _CHECKPOINT_REF
    assert HarnessGraphActivityExecutionInput.from_dict(
        execution_input.to_dict()
    ) == execution_input
    assert HarnessGraphActivity.from_dict(activity.to_dict()) == activity


def test_dispatcher_recovery_requires_current_node_output_commit() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    execution_input = _execution_input(activity, task)
    executor = _executor(
        execution_input=execution_input,
        worker=worker,
        resource=resource,
        committer=_ResultCommitter(),
    )
    recorded = []
    applied = []
    existing = HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output={"report": {"value": "candidate"}},
    )
    dispatcher = HarnessGraphPhysicalActivityDispatcher(
        executor=executor,
        graph_resolver=lambda _activity: HarnessGraphCompiler().compile(
            build_paper_analysis_graph_definition()
        ).graph,
        input_resolver=_InputResolver(execution_input),
        accept=lambda _activity, _input: existing,
        record_call_marker=lambda _activity, _input: None,
        record_result=lambda activity, _graph, _worker: recorded.append(activity)
        or HarnessEvent(
            event_type=HarnessEventType.GRAPH_WORKER_RESULT_RECORDED,
            run_id=activity.run_id,
            node_id=activity.node_id,
        ),
        apply_result=lambda activity, worker_result, result: applied.append(
            (activity, worker_result, result)
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        dispatcher.dispatch(activity)

    assert captured.value.code == "graph_physical_result_commit_missing"
    assert worker.calls == []
    assert recorded == []
    assert applied == []


def test_dispatcher_recovery_uses_exact_current_commit_and_not_worker_candidate_ref() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    execution_input = _execution_input(activity, task)
    executor = _executor(
        execution_input=execution_input,
        worker=worker,
        resource=resource,
        committer=_ResultCommitter(),
    )
    first = executor.execute(activity, attempt_id="physical-attempt-1")
    assert first.node_output_commit is not None
    assert first.worker_result is not None
    recorded = []
    applied = []
    dispatcher = HarnessGraphPhysicalActivityDispatcher(
        executor=executor,
        graph_resolver=lambda _activity: HarnessGraphCompiler().compile(
            build_paper_analysis_graph_definition()
        ).graph,
        input_resolver=_InputResolver(execution_input),
        accept=lambda _activity, _input: first.worker_result,
        record_call_marker=lambda _activity, _input: None,
        record_result=lambda activity, _graph, _worker: recorded.append(activity)
        or HarnessEvent(
            event_type=HarnessEventType.GRAPH_WORKER_RESULT_RECORDED,
            run_id=activity.run_id,
            node_id=activity.node_id,
        ),
        apply_result=lambda activity, worker_result, result: applied.append(
            (activity, worker_result, result)
        ),
    )

    dispatcher.dispatch(activity)

    assert len(worker.calls) == 1
    assert len(recorded) == 1
    assert len(applied) == 1
    _, recovered_worker, recovered_result = applied[0]
    assert recovered_worker == first.worker_result
    assert recovered_result.payload_ref == first.node_output_commit.candidate.candidate_ref
    assert recovered_result.payload_ref != first.worker_result.candidate_result_ref


def test_dispatcher_consumes_cancellation_requested_before_dispatch() -> None:
    activity, task = _activity_and_task()
    execution_input = _execution_input(activity, task)
    executor = _executor(
        execution_input=execution_input,
        worker=_Worker(),
        resource=InMemoryHarnessNodeOutputResource(),
        committer=_ResultCommitter(),
    )
    observed: dict[str, object] = {}

    def execute(_activity, *, cancel_event=None, **_kwargs):
        observed["cancel_event"] = cancel_event
        assert cancel_event is not None and cancel_event.is_set()
        raise RuntimeError("cancelled before physical start")

    executor.execute = execute
    dispatcher = _dispatcher_for(executor, execution_input)
    request = _cancellation_request(activity)
    dispatcher.request_cancellation(request)

    with pytest.raises(RuntimeError, match="cancelled before physical start"):
        dispatcher.dispatch(activity)

    assert isinstance(observed["cancel_event"], threading.Event)


def test_dispatcher_sets_active_cancellation_event_during_physical_execution() -> None:
    activity, task = _activity_and_task()
    execution_input = _execution_input(activity, task)
    executor = _executor(
        execution_input=execution_input,
        worker=_Worker(),
        resource=InMemoryHarnessNodeOutputResource(),
        committer=_ResultCommitter(),
    )
    started = threading.Event()
    cancellation_observed = threading.Event()
    errors: list[BaseException] = []

    def execute(_activity, *, cancel_event=None, **_kwargs):
        assert cancel_event is not None
        started.set()
        if cancel_event.wait(timeout=2):
            cancellation_observed.set()
        raise RuntimeError("cooperative cancellation observed")

    executor.execute = execute
    dispatcher = _dispatcher_for(executor, execution_input)
    request = _cancellation_request(activity)

    def run_dispatch() -> None:
        try:
            dispatcher.dispatch(activity)
        except BaseException as exc:  # thread assertions are reported below
            errors.append(exc)

    worker_thread = threading.Thread(target=run_dispatch)
    worker_thread.start()
    assert started.wait(timeout=2)
    dispatcher.request_cancellation(request)
    worker_thread.join(timeout=2)

    assert not worker_thread.is_alive()
    assert cancellation_observed.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


def _dispatcher_for(
    executor: HarnessGraphPhysicalActivityExecutor,
    execution_input: HarnessGraphActivityExecutionInput,
) -> HarnessGraphPhysicalActivityDispatcher:
    graph = HarnessGraphCompiler().compile(
        build_paper_analysis_graph_definition()
    ).graph
    return HarnessGraphPhysicalActivityDispatcher(
        executor=executor,
        graph_resolver=lambda _activity: graph,
        input_resolver=_InputResolver(execution_input),
        accept=lambda _activity, _input: None,
        record_call_marker=lambda _activity, _input: None,
        record_result=lambda _activity, _graph, _worker: None,
        apply_result=lambda _activity, _worker, _result: None,
    )


def _cancellation_request(
    activity: HarnessGraphActivity,
) -> HarnessGraphActivityCancellationRequest:
    return HarnessGraphActivityCancellationRequest(
        run_id=activity.run_id,
        activity_id=activity.activity_id,
        node_instance_id=activity.node_instance_id,
        attempt=activity.attempt,
        idempotency_key=activity.idempotency_key,
        fencing_generation=activity.fencing_generation,
        causal_decision_checksum=checksum_for({"decision": "cancel"}),
        reason_code="parallel_any_sibling_failed",
    )


def test_deadline_rejection_emits_no_lease_worker_call_or_result() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    clock = lambda: 10.0
    executor = _executor(
        execution_input=_execution_input(activity, task, timeout_seconds=1.0),
        worker=worker,
        resource=resource,
        committer=committer,
        supervisor=AttemptSupervisor(clock=clock),
    )
    parent = AttemptContext.create(
        attempt_id="parent-attempt",
        idempotency_key="graph-run:parent",
        operation_id="graph-run:parent",
        operation_kind="graph_run",
        deadline=10.5,
        clock=clock,
    )

    receipt = executor.execute(
        activity,
        parent_context=parent,
        admission_policy=DeadlineAdmissionPolicy(
            timeout_seconds=1.0,
            min_start_window_seconds=1.0,
        ),
    )

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert receipt.attempt is not None
    assert receipt.attempt.outcome.state is AttemptState.REJECTED
    assert receipt.attempt.admission is None
    assert receipt.attempt.lease is None
    assert receipt.node_output_commit is None
    assert receipt.graph_result is None
    assert worker.calls == []
    assert committer.calls == []
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None


def test_capability_admission_fails_before_lease_or_worker_execution() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    execution_input = _execution_input(
        activity,
        task,
        required_usage=HarnessActivityUsage.PARALLEL,
    )
    executor = _executor(
        execution_input=execution_input,
        worker=worker,
        activity_contract=_ActivityContract(
            capabilities=HarnessActivityCapabilities(stable_idempotency=True)
        ),
        resource=resource,
        committer=committer,
    )

    with pytest.raises(HarnessValidationError) as captured:
        executor.execute(activity)

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert captured.value.code == "activity_contract_safety_unproven"
    assert worker.calls == []
    assert committer.calls == []
    assert resource.current_lease(identity) is None


def test_resolved_input_checksum_mismatch_fails_before_binding_admission() -> None:
    activity, task = _activity_and_task()
    mismatched = HarnessGraphActivityExecutionInput(
        activity_id=activity.activity_id,
        activity_checksum=activity.activity_checksum,
        task={**task, "inputs": {"source": "forged"}},
        leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
        required_usage=HarnessActivityUsage.SERIAL,
        graph_checkpoint_ref=_CHECKPOINT_REF,
        output_keys=("report",),
    )
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    executor = _executor(
        execution_input=mismatched,
        worker=worker,
        resource=resource,
        committer=committer,
    )

    with pytest.raises(HarnessValidationError) as captured:
        executor.execute(activity)

    assert captured.value.code == "graph_activity_execution_input_mismatch"
    assert captured.value.details == {"mismatches": ["input_ref"]}
    assert worker.calls == []
    assert committer.calls == []


def test_failed_worker_revokes_lease_and_commits_only_failed_graph_result() -> None:
    activity, task = _activity_and_task()
    worker_result = HarnessWorkerResult(
        status=HarnessWorkerStatus.FAILED,
        error="candidate generation failed",
    )
    worker = _Worker(lambda _task: worker_result)
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    executor = _executor(
        execution_input=_execution_input(activity, task),
        worker=worker,
        resource=resource,
        committer=committer,
    )

    receipt = executor.execute(activity, attempt_id="physical-attempt-1")

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert receipt.attempt is not None
    assert receipt.attempt.outcome.state is AttemptState.FAILED
    assert receipt.node_output_commit is None
    assert receipt.graph_result is not None
    assert receipt.graph_result.status is HarnessGraphActivityResultStatus.FAILED
    assert receipt.graph_result.payload_ref == worker_result.candidate_result_ref
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None
    assert len(committer.calls) == 1
    assert committer.calls[0]["node_output_commit"] is None


def test_indeterminate_attempt_never_commits_normal_node_output() -> None:
    activity, task = _activity_and_task()

    def indeterminate(_task):
        context = current_attempt_context()
        assert context is not None
        context.mark_descendant_indeterminate()
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            output={"report": {"value": "must-not-publish"}},
        )

    worker = _Worker(indeterminate)
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    executor = _executor(
        execution_input=_execution_input(activity, task),
        worker=worker,
        resource=resource,
        committer=committer,
    )

    receipt = executor.execute(activity, attempt_id="physical-attempt-1")

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert receipt.attempt is not None
    assert receipt.attempt.outcome.state is AttemptState.INDETERMINATE
    assert receipt.node_output_commit is None
    assert receipt.graph_result is not None
    assert (
        receipt.graph_result.status
        is HarnessGraphActivityResultStatus.INDETERMINATE
    )
    assert resource.current_lease(identity) is None
    assert resource.committed_output(identity) is None


def test_superseded_physical_attempt_cannot_commit_output_or_graph_result() -> None:
    activity, task = _activity_and_task()
    resource = InMemoryHarnessNodeOutputResource()

    def supersede(_task):
        resource.acquire_after_admission(
            activity,
            HarnessAdmittedGraphActivityAttempt(
                activity_id=activity.activity_id,
                activity_checksum=activity.activity_checksum,
                owner_attempt_id="physical-attempt-2",
                operation_id="graph-activity://replacement",
                operation_kind="graph_activity",
                idempotency_key=activity.idempotency_key,
                local_attempt_no=1,
                parent_attempt_id=None,
                retry_credit_id=None,
                admitted_at=_NOW,
            ),
        )
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.SUCCEEDED,
            output={"report": {"value": "stale"}},
        )

    worker = _Worker(supersede)
    committer = _ResultCommitter()
    executor = _executor(
        execution_input=_execution_input(activity, task),
        worker=worker,
        resource=resource,
        committer=committer,
    )

    receipt = executor.execute(activity, attempt_id="physical-attempt-1")

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    assert receipt.attempt is not None
    assert receipt.attempt.outcome.state is AttemptState.INDETERMINATE
    assert receipt.node_output_commit is None
    assert receipt.graph_result is None
    assert committer.calls == []
    assert resource.committed_output(identity) is None
    assert resource.current_lease(identity) is not None
    assert resource.current_lease(identity).owner_attempt_id == "physical-attempt-2"


def test_committed_output_reconciles_result_failure_without_worker_reexecution() -> None:
    activity, task = _activity_and_task()
    worker = _Worker()
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter(fail_once=True)
    executor = _executor(
        execution_input=_execution_input(activity, task),
        worker=worker,
        resource=resource,
        committer=committer,
    )

    with pytest.raises(OSError, match="result store unavailable"):
        executor.execute(activity, attempt_id="physical-attempt-1")

    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    committed_output = resource.committed_output(identity)
    assert committed_output is not None
    assert len(worker.calls) == 1

    recovered = executor.execute(activity, attempt_id="must-not-be-used")

    assert recovered.recovered_output is True
    assert recovered.attempt is None
    assert recovered.worker_result is not None
    assert recovered.worker_result.to_dict() == committed_output.candidate.worker_result
    assert recovered.node_output_commit == committed_output
    assert recovered.graph_result is not None
    assert recovered.graph_result.status is HarnessGraphActivityResultStatus.SUCCEEDED
    assert len(worker.calls) == 1
    assert len(committer.calls) == 2
    assert committer.calls[1]["worker_result"] == recovered.worker_result


def test_recovery_rejects_commit_outside_declared_output_contract() -> None:
    activity, task = _activity_and_task()
    resource = InMemoryHarnessNodeOutputResource()
    HarnessAdmittedGraphActivityOutputAdapter(
        resource=resource,
        supervisor=AttemptSupervisor(),
        clock=lambda: _NOW,
    ).run(
        lambda: HarnessNodeOutputCandidate(
            output_refs={"undeclared": checksum_for({"value": "wrong"})},
            evidence_refs=(checksum_for({"evidence": "wrong"}),),
        ),
        activity=activity,
        timeout_seconds=None,
        attempt_id="foreign-physical-attempt",
    )
    worker = _Worker()
    committer = _ResultCommitter()
    executor = _executor(
        execution_input=_execution_input(activity, task),
        worker=worker,
        resource=resource,
        committer=committer,
    )

    with pytest.raises(HarnessValidationError) as captured:
        executor.execute(activity)

    assert captured.value.code == "graph_physical_activity_output_mismatch"
    assert captured.value.details == {"mismatches": ["output_keys"]}
    assert worker.calls == []
    assert committer.calls == []


def test_execution_input_rejects_caller_supplied_harness_context() -> None:
    activity, task = _activity_and_task()

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphActivityExecutionInput(
            activity_id=activity.activity_id,
            activity_checksum=activity.activity_checksum,
            task={**task, HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY: {}},
            leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
            required_usage=HarnessActivityUsage.SERIAL,
            graph_checkpoint_ref=_CHECKPOINT_REF,
            output_keys=("report",),
        )

    assert captured.value.code == "graph_activity_task_context_reserved"


def test_checkpoint_bound_context_and_activity_reject_checksum_tamper() -> None:
    activity, task = _activity_and_task()
    execution_input = _execution_input(activity, task)
    context = HarnessGraphActivityTaskContext.for_execution_input(
        activity,
        execution_input,
    )

    assert HarnessGraphActivityTaskContext.from_dict(context.to_dict()) == context

    tampered_context = context.to_dict()
    tampered_context["graph_checkpoint_ref"] = "checkpoint://run-1/forged"
    with pytest.raises(HarnessValidationError) as context_error:
        HarnessGraphActivityTaskContext.from_dict(tampered_context)
    assert (
        context_error.value.code
        == "graph_activity_task_context_checksum_invalid"
    )

    tampered_input = execution_input.to_dict()
    tampered_input["graph_checkpoint_ref"] = "checkpoint://run-1/forged"
    with pytest.raises(HarnessValidationError) as input_error:
        HarnessGraphActivityExecutionInput.from_dict(tampered_input)
    assert input_error.value.code == "graph_activity_execution_input_checksum_invalid"

    tampered_activity = activity.to_dict()
    tampered_activity["attempt"] = 2
    with pytest.raises(HarnessValidationError) as activity_error:
        HarnessGraphActivity.from_dict(tampered_activity)
    assert activity_error.value.code == "graph_activity_checksum_invalid"


def _executor(
    *,
    execution_input: HarnessGraphActivityExecutionInput,
    worker: _Worker,
    resource: InMemoryHarnessNodeOutputResource,
    committer: _ResultCommitter,
    activity_contract: _ActivityContract | None = None,
    supervisor: AttemptSupervisor | None = None,
) -> HarnessGraphPhysicalActivityExecutor:
    activity_contract = activity_contract or _ActivityContract(
        capabilities=HarnessActivityCapabilities(stable_idempotency=True)
    )
    authority = HarnessRuntimeBindingAuthority(
        workers=(
            HarnessWorkerBinding(
                reference=_WORKER_REF,
                worker_type=HarnessWorkerType.FUNCTION,
                implementation=worker,
            ),
        ),
        activities=(
            HarnessActivityContractBinding(
                reference=_ACTIVITY_REF,
                implementation=activity_contract,
            ),
        ),
        leaf_activities=(
            HarnessLeafActivityBinding(
                leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
                worker_ref=_WORKER_REF,
                activity_ref=_ACTIVITY_REF,
            ),
        ),
    )
    return HarnessGraphPhysicalActivityExecutor(
        binding_authority=authority,
        input_resolver=_InputResolver(execution_input),
        node_output_resource=resource,
        result_committer=committer,
        supervisor=supervisor or AttemptSupervisor(),
        clock=lambda: _NOW,
    )


def _execution_input(
    activity: HarnessGraphActivity,
    task: dict[str, Any],
    *,
    required_usage: HarnessActivityUsage = HarnessActivityUsage.SERIAL,
    timeout_seconds: float | None = None,
) -> HarnessGraphActivityExecutionInput:
    return HarnessGraphActivityExecutionInput.for_activity(
        activity,
        task=task,
        leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
        required_usage=required_usage,
        graph_checkpoint_ref=_CHECKPOINT_REF,
        output_keys=("report",),
        timeout_seconds=timeout_seconds,
    )


def _activity_and_task() -> tuple[HarnessGraphActivity, dict[str, Any]]:
    task = {
        "run_id": "run-1",
        "step_id": "analyze",
        "worker_type": HarnessWorkerType.FUNCTION.value,
        "inputs": {"source": "paper"},
        "metadata": {"candidate_only": True},
    }
    activity = HarnessGraphActivity(
        run_id="run-1",
        graph_ref=HarnessGraphReference(
            graph_id="test.graph",
            schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
            compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
            condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
            checksum=checksum_for({"graph": "test"}),
            graph_ref=HarnessContractReference(
                HarnessContractKind.GRAPH,
                "test.graph",
                "1",
            ),
        ),
        node_id="analyze",
        node_instance_id="hni-analyze-1",
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            "test.analyze",
            "1",
        ),
        worker_ref=_WORKER_REF,
        activity_ref=_ACTIVITY_REF,
        attempt=1,
        input_ref=graph_activity_input_checksum(task),
        causal_decision_checksum=checksum_for({"decision": "dispatch"}),
        causal_decision_sequence=3,
        fencing_generation=1,
        tenant_scope_ref=checksum_for({"tenant": "tenant-1"}),
        identity_scope_ref=checksum_for({"identity": "worker-1"}),
        subject_scope_ref=checksum_for({"subject": "paper-1"}),
    )
    return activity, task
