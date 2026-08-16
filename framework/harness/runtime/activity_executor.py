from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.activity import (
    harness_activity_input_checksum,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultStatus,
)
from framework.harness.control_plane.node_output import (
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputResourceIdentity,
    HarnessNodeOutputResourcePort,
)
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
)
from framework.harness.graph.bindings import (
    HarnessActivityUsage,
    HarnessRuntimeBindingAuthority,
)
from framework.harness.graph.canonical import (
    canonical_checksum,
    freeze_json,
    mapping_to_dict,
    required_text,
)
from framework.harness.runtime.node_output import (
    HarnessAdmittedGraphActivityOutputAdapter,
    HarnessGraphActivityOutputAttemptResult,
)
from framework.harness.workers.result import (
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.shared.attempts import (
    AttemptContext,
    AttemptLifecycleSink,
    AttemptSupervisor,
    AttemptState,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
)
from framework.shared.time import utc_now


HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA = (
    "newsroom.harness-graph-activity-execution-input/v1"
)
HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA = (
    "newsroom.harness-graph-activity-failure-evidence/v1"
)
HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY = "harness_graph_activity"

_RESERVED_TASK_KEYS = frozenset(
    {
        HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
        "harness_activity",
    }
)


@dataclass(frozen=True, slots=True)
class HarnessGraphActivityExecutionInput:
    """Checksum-bound physical input resolved for one durable Graph activity."""

    activity_id: str
    activity_checksum: str
    task: Mapping[str, Any]
    leaf_activity_kind: HarnessLeafActivityKind | str
    required_usage: HarnessActivityUsage | str
    output_keys: tuple[str, ...]
    timeout_seconds: float | None = None
    schema_version: str = HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA
    input_ref: str = field(init=False)
    binding_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "activity_id",
            required_text(self.activity_id, "activity_execution_input.activity_id"),
        )
        object.__setattr__(
            self,
            "activity_checksum",
            _checksum(
                self.activity_checksum,
                "activity_execution_input.activity_checksum",
            ),
        )
        if not isinstance(self.task, Mapping):
            raise HarnessValidationError(
                "Graph activity execution task must be an object",
                code="graph_activity_execution_input_invalid",
            )
        task = freeze_json(
            dict(self.task),
            "$.graph_activity_execution_input.task",
        )
        if not isinstance(task, Mapping):  # pragma: no cover - guarded above
            raise AssertionError("canonical Graph activity task must remain a mapping")
        reserved = sorted(set(task).intersection(_RESERVED_TASK_KEYS))
        if reserved:
            raise HarnessValidationError(
                "Graph activity task cannot supply Harness-owned activity context",
                code="graph_activity_task_context_reserved",
                details={"keys": reserved},
            )
        object.__setattr__(self, "task", task)
        try:
            leaf_kind = HarnessLeafActivityKind(self.leaf_activity_kind)
            required_usage = HarnessActivityUsage(self.required_usage)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "Graph activity execution binding is unsupported",
                code="graph_activity_execution_binding_invalid",
            ) from exc
        object.__setattr__(self, "leaf_activity_kind", leaf_kind)
        object.__setattr__(self, "required_usage", required_usage)
        output_keys = _output_keys(self.output_keys)
        object.__setattr__(self, "output_keys", output_keys)
        timeout_seconds = self.timeout_seconds
        if timeout_seconds is not None:
            if (
                isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, int | float)
                or not math.isfinite(float(timeout_seconds))
                or float(timeout_seconds) <= 0
            ):
                raise HarnessValidationError(
                    "Graph activity timeout must be finite and positive",
                    code="graph_activity_execution_timeout_invalid",
                )
            timeout_seconds = float(timeout_seconds)
            object.__setattr__(self, "timeout_seconds", timeout_seconds)
        if self.schema_version != HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph activity execution input schema",
                code="unsupported_graph_activity_execution_input_schema",
            )
        input_ref = harness_activity_input_checksum(mapping_to_dict(task))
        object.__setattr__(self, "input_ref", input_ref)
        object.__setattr__(
            self,
            "binding_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    @classmethod
    def for_activity(
        cls,
        activity: HarnessGraphActivity,
        *,
        task: Mapping[str, Any],
        leaf_activity_kind: HarnessLeafActivityKind | str,
        required_usage: HarnessActivityUsage | str,
        output_keys: tuple[str, ...],
        timeout_seconds: float | None = None,
    ) -> HarnessGraphActivityExecutionInput:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        value = cls(
            activity_id=activity.activity_id,
            activity_checksum=activity.activity_checksum,
            task=task,
            leaf_activity_kind=leaf_activity_kind,
            required_usage=required_usage,
            output_keys=output_keys,
            timeout_seconds=timeout_seconds,
        )
        value.assert_matches(activity)
        return value

    def assert_matches(self, activity: HarnessGraphActivity) -> None:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        mismatches = tuple(
            field_name
            for field_name, expected, actual in (
                ("activity_id", activity.activity_id, self.activity_id),
                (
                    "activity_checksum",
                    activity.activity_checksum,
                    self.activity_checksum,
                ),
                ("input_ref", activity.input_ref, self.input_ref),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "resolved execution input conflicts with its durable Graph activity",
                code="graph_activity_execution_input_mismatch",
                details={"mismatches": list(mismatches)},
            )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activity_id": self.activity_id,
            "activity_checksum": self.activity_checksum,
            "task": mapping_to_dict(self.task),
            "leaf_activity_kind": self.leaf_activity_kind.value,
            "required_usage": self.required_usage.value,
            "output_keys": list(self.output_keys),
            "timeout_seconds": self.timeout_seconds,
            "input_ref": self.input_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "binding_checksum": self.binding_checksum,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> HarnessGraphActivityExecutionInput:
        expected = {
            "schema_version",
            "activity_id",
            "activity_checksum",
            "task",
            "leaf_activity_kind",
            "required_usage",
            "output_keys",
            "timeout_seconds",
            "input_ref",
            "binding_checksum",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise HarnessValidationError(
                "Graph activity execution input fields are invalid",
                code="graph_activity_execution_input_invalid",
            )
        output_keys = value["output_keys"]
        if isinstance(output_keys, str | bytes) or not isinstance(
            output_keys,
            Sequence,
        ):
            raise HarnessValidationError(
                "Graph activity execution output keys must be an array",
                code="graph_activity_execution_input_invalid",
            )
        restored = cls(
            activity_id=value["activity_id"],
            activity_checksum=value["activity_checksum"],
            task=value["task"],
            leaf_activity_kind=value["leaf_activity_kind"],
            required_usage=value["required_usage"],
            output_keys=tuple(output_keys),
            timeout_seconds=value["timeout_seconds"],
            schema_version=value["schema_version"],
        )
        if (
            value["input_ref"] != restored.input_ref
            or value["binding_checksum"] != restored.binding_checksum
        ):
            raise HarnessValidationError(
                "Graph activity execution input checksum is invalid",
                code="graph_activity_execution_input_checksum_invalid",
            )
        return restored


@runtime_checkable
class HarnessGraphActivityExecutionInputResolverPort(Protocol):
    def resolve_execution_input(
        self,
        activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        """Resolve immutable input already bound to the activity input ref."""
        ...


@runtime_checkable
class HarnessGraphActivityExecutionCommitPort(Protocol):
    def commit_execution_result(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        worker_result: HarnessWorkerResult | None,
        node_output_commit: HarnessNodeOutputCommit | None,
        result: HarnessGraphActivityResult,
    ) -> HarnessGraphActivityResult:
        """Idempotently commit one activity-bound result and return its fact."""
        ...


@dataclass(frozen=True, slots=True)
class HarnessGraphPhysicalActivityExecutionResult:
    activity: HarnessGraphActivity
    execution_input: HarnessGraphActivityExecutionInput
    attempt: HarnessGraphActivityOutputAttemptResult | None
    worker_result: HarnessWorkerResult | None
    node_output_commit: HarnessNodeOutputCommit | None
    graph_result: HarnessGraphActivityResult | None
    recovered_output: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if not isinstance(
            self.execution_input,
            HarnessGraphActivityExecutionInput,
        ):
            raise TypeError(
                "execution_input must be HarnessGraphActivityExecutionInput"
            )
        self.execution_input.assert_matches(self.activity)
        if self.attempt is not None and not isinstance(
            self.attempt,
            HarnessGraphActivityOutputAttemptResult,
        ):
            raise TypeError("attempt must be HarnessGraphActivityOutputAttemptResult")
        if self.worker_result is not None and not isinstance(
            self.worker_result,
            HarnessWorkerResult,
        ):
            raise TypeError("worker_result must be HarnessWorkerResult")
        if self.node_output_commit is not None:
            if not isinstance(self.node_output_commit, HarnessNodeOutputCommit):
                raise TypeError("node_output_commit must be HarnessNodeOutputCommit")
            if self.node_output_commit.activity_id != self.activity.activity_id:
                raise HarnessValidationError(
                    "physical execution cannot claim another activity's node output",
                    code="graph_physical_activity_output_mismatch",
                )
        if self.graph_result is not None:
            if not isinstance(self.graph_result, HarnessGraphActivityResult):
                raise TypeError("graph_result must be HarnessGraphActivityResult")
            _assert_result_matches_activity(self.graph_result, self.activity)
            if (
                self.graph_result.status
                is HarnessGraphActivityResultStatus.SUCCEEDED
                and self.node_output_commit is None
            ):
                raise HarnessValidationError(
                    "successful physical execution requires committed node output",
                    code="graph_physical_activity_result_invalid",
                )
        if self.recovered_output:
            if (
                self.attempt is not None
                or self.worker_result is not None
                or self.node_output_commit is None
                or self.graph_result is None
            ):
                raise HarnessValidationError(
                    "recovered physical execution receipt is inconsistent",
                    code="graph_physical_activity_result_invalid",
                )
        elif self.attempt is None:
            raise HarnessValidationError(
                "new physical execution receipt requires an attempt outcome",
                code="graph_physical_activity_result_invalid",
            )


class HarnessGraphPhysicalActivityExecutor:
    """Inactive Graph-native physical dispatcher for candidate-only leaves.

    The executor consumes a durable ``HarnessGraphActivity`` and never invokes
    ``HarnessActivityContractBinding.implementation.dispatch``. Exact pair and
    capability admission remain composition-owned through the runtime binding
    authority. Production composition must not install this executor until its
    input, node-output, and result ports are durable.
    """

    def __init__(
        self,
        *,
        binding_authority: HarnessRuntimeBindingAuthority,
        input_resolver: HarnessGraphActivityExecutionInputResolverPort,
        node_output_resource: HarnessNodeOutputResourcePort,
        result_committer: HarnessGraphActivityExecutionCommitPort,
        supervisor: AttemptSupervisor,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(binding_authority, HarnessRuntimeBindingAuthority):
            raise TypeError(
                "binding_authority must be HarnessRuntimeBindingAuthority"
            )
        if not isinstance(
            input_resolver,
            HarnessGraphActivityExecutionInputResolverPort,
        ):
            raise TypeError(
                "input_resolver must implement "
                "HarnessGraphActivityExecutionInputResolverPort"
            )
        if not isinstance(node_output_resource, HarnessNodeOutputResourcePort):
            raise TypeError(
                "node_output_resource must implement HarnessNodeOutputResourcePort"
            )
        if not isinstance(
            result_committer,
            HarnessGraphActivityExecutionCommitPort,
        ):
            raise TypeError(
                "result_committer must implement "
                "HarnessGraphActivityExecutionCommitPort"
            )
        if not isinstance(supervisor, AttemptSupervisor):
            raise TypeError("supervisor must be AttemptSupervisor")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._binding_authority = binding_authority
        self._input_resolver = input_resolver
        self._node_output_resource = node_output_resource
        self._result_committer = result_committer
        self._output_adapter = HarnessAdmittedGraphActivityOutputAdapter(
            resource=node_output_resource,
            supervisor=supervisor,
            clock=clock,
        )

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        """Execute one already committed Graph activity descriptor."""

        self.execute(activity)

    def execute(
        self,
        activity: HarnessGraphActivity,
        *,
        attempt_id: str | None = None,
        local_budget: LocalRetryBudget | None = None,
        retry_ledger: RetryCreditLedger | None = None,
        admission_policy: DeadlineAdmissionPolicy | None = None,
        execution_limits: ExecutionLimits | None = None,
        parent_context: AttemptContext | None = None,
        cancel_event: threading.Event | None = None,
        parent_cancel_event: threading.Event | None = None,
        event_sink: AttemptLifecycleSink | None = None,
    ) -> HarnessGraphPhysicalActivityExecutionResult:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        execution_input = self._input_resolver.resolve_execution_input(activity)
        if not isinstance(execution_input, HarnessGraphActivityExecutionInput):
            raise HarnessValidationError(
                "Graph activity input resolver returned an invalid contract",
                code="graph_activity_execution_input_invalid",
            )
        execution_input.assert_matches(activity)
        binding = self._binding_authority.resolve_leaf_activity(
            worker_ref=activity.worker_ref,
            activity_ref=activity.activity_ref,
            expected_leaf_activity_kind=execution_input.leaf_activity_kind,
            required_usage=execution_input.required_usage,
        )
        if (
            binding.worker.reference != activity.worker_ref
            or binding.activity.reference != activity.activity_ref
        ):
            raise HarnessValidationError(
                "resolved physical binding conflicts with the Graph activity",
                code="graph_physical_activity_binding_mismatch",
            )

        resource_identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
        existing = self._node_output_resource.committed_output(resource_identity)
        if existing is not None:
            return self._recover_committed_output(
                activity,
                execution_input,
                existing,
            )

        worker_holder: dict[str, HarnessWorkerResult] = {}

        def invoke() -> HarnessNodeOutputCandidate:
            worker_result = _coerce_worker_result(
                binding.worker.implementation.execute(
                    _worker_task(execution_input, activity)
                )
            )
            worker_holder["value"] = worker_result
            if worker_result.status is not HarnessWorkerStatus.SUCCEEDED:
                raise HarnessValidationError(
                    "Graph worker did not produce a successful candidate",
                    code="graph_activity_worker_candidate_failed",
                    details={"worker_status": worker_result.status.value},
                )
            return _node_output_candidate(execution_input, worker_result)

        attempt = self._output_adapter.run(
            invoke,
            activity=activity,
            timeout_seconds=execution_input.timeout_seconds,
            attempt_id=attempt_id,
            local_budget=local_budget,
            retry_ledger=retry_ledger,
            admission_policy=admission_policy,
            execution_limits=execution_limits,
            parent_context=parent_context,
            cancel_event=cancel_event,
            parent_cancel_event=parent_cancel_event,
            event_sink=event_sink,
        )
        worker_result = worker_holder.get("value")
        commit = attempt.commit
        current_commit = self._node_output_resource.committed_output(
            resource_identity
        )
        if commit is None and current_commit is not None:
            if current_commit.activity_id == activity.activity_id:
                commit = current_commit
            else:
                return HarnessGraphPhysicalActivityExecutionResult(
                    activity=activity,
                    execution_input=execution_input,
                    attempt=attempt,
                    worker_result=worker_result,
                    node_output_commit=None,
                    graph_result=None,
                )
        if commit is not None:
            _assert_output_commit_matches(activity, execution_input, commit)
            result = _successful_activity_result(activity, commit)
            committed_result = self._commit_result(
                activity=activity,
                execution_input=execution_input,
                worker_result=worker_result,
                node_output_commit=commit,
                result=result,
            )
            return HarnessGraphPhysicalActivityExecutionResult(
                activity=activity,
                execution_input=execution_input,
                attempt=attempt,
                worker_result=worker_result,
                node_output_commit=commit,
                graph_result=committed_result,
            )
        if not attempt.outcome.started:
            return HarnessGraphPhysicalActivityExecutionResult(
                activity=activity,
                execution_input=execution_input,
                attempt=attempt,
                worker_result=None,
                node_output_commit=None,
                graph_result=None,
            )
        current_lease = self._node_output_resource.current_lease(resource_identity)
        if (
            current_lease is not None
            and attempt.lease is not None
            and current_lease.lease_ref != attempt.lease.lease_ref
        ):
            return HarnessGraphPhysicalActivityExecutionResult(
                activity=activity,
                execution_input=execution_input,
                attempt=attempt,
                worker_result=worker_result,
                node_output_commit=None,
                graph_result=None,
            )

        result = _failed_activity_result(activity, attempt, worker_result)
        committed_result = self._commit_result(
            activity=activity,
            execution_input=execution_input,
            worker_result=worker_result,
            node_output_commit=None,
            result=result,
        )
        return HarnessGraphPhysicalActivityExecutionResult(
            activity=activity,
            execution_input=execution_input,
            attempt=attempt,
            worker_result=worker_result,
            node_output_commit=None,
            graph_result=committed_result,
        )

    def _recover_committed_output(
        self,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        commit: HarnessNodeOutputCommit,
    ) -> HarnessGraphPhysicalActivityExecutionResult:
        _assert_output_commit_matches(activity, execution_input, commit)
        result = _successful_activity_result(activity, commit)
        committed_result = self._commit_result(
            activity=activity,
            execution_input=execution_input,
            worker_result=None,
            node_output_commit=commit,
            result=result,
        )
        return HarnessGraphPhysicalActivityExecutionResult(
            activity=activity,
            execution_input=execution_input,
            attempt=None,
            worker_result=None,
            node_output_commit=commit,
            graph_result=committed_result,
            recovered_output=True,
        )

    def _commit_result(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        worker_result: HarnessWorkerResult | None,
        node_output_commit: HarnessNodeOutputCommit | None,
        result: HarnessGraphActivityResult,
    ) -> HarnessGraphActivityResult:
        committed = self._result_committer.commit_execution_result(
            activity=activity,
            execution_input=execution_input,
            worker_result=worker_result,
            node_output_commit=node_output_commit,
            result=result,
        )
        if not isinstance(committed, HarnessGraphActivityResult) or committed != result:
            raise HarnessValidationError(
                "Graph activity result committer returned a conflicting fact",
                code="graph_activity_result_commit_mismatch",
            )
        return committed


def _worker_task(
    execution_input: HarnessGraphActivityExecutionInput,
    activity: HarnessGraphActivity,
) -> dict[str, Any]:
    return {
        **mapping_to_dict(execution_input.task),
        HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY: activity.to_dict(),
    }


def _coerce_worker_result(value: Any) -> HarnessWorkerResult:
    if isinstance(value, HarnessWorkerResult):
        return value
    to_dict = getattr(value, "to_dict", None)
    payload = to_dict() if callable(to_dict) else value
    if not isinstance(payload, Mapping):
        raise HarnessValidationError(
            "Graph worker returned an invalid candidate result",
            code="invalid_worker_result",
        )
    return HarnessWorkerResult.from_dict(payload)


def _node_output_candidate(
    execution_input: HarnessGraphActivityExecutionInput,
    worker_result: HarnessWorkerResult,
) -> HarnessNodeOutputCandidate:
    if set(worker_result.output) != set(execution_input.output_keys):
        raise HarnessValidationError(
            "Graph worker outputs do not match the physical activity contract",
            code="graph_activity_worker_output_mismatch",
            details={
                "expected_output_keys": sorted(execution_input.output_keys),
                "actual_output_keys": sorted(worker_result.output),
            },
        )
    output_refs = {
        output_key: canonical_checksum(worker_result.output[output_key])
        for output_key in execution_input.output_keys
    }
    evidence_refs = tuple(
        sorted(
            {
                worker_result.candidate_result_ref,
                *(item.evidence_checksum for item in worker_result.evidence),
            }
        )
    )
    return HarnessNodeOutputCandidate(
        output_refs=output_refs,
        evidence_refs=evidence_refs,
    )


def _successful_activity_result(
    activity: HarnessGraphActivity,
    commit: HarnessNodeOutputCommit,
) -> HarnessGraphActivityResult:
    if commit.activity_id != activity.activity_id:
        raise HarnessValidationError(
            "node-output commit does not belong to the Graph activity",
            code="graph_physical_activity_output_mismatch",
        )
    return HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=commit.commit_ref,
        payload_ref=commit.candidate.candidate_ref,
        status=HarnessGraphActivityResultStatus.SUCCEEDED,
        termination_confirmed=True,
    )


def _assert_output_commit_matches(
    activity: HarnessGraphActivity,
    execution_input: HarnessGraphActivityExecutionInput,
    commit: HarnessNodeOutputCommit,
) -> None:
    resource = HarnessNodeOutputResourceIdentity.for_activity(activity)
    if commit.activity_id != activity.activity_id:
        raise HarnessValidationError(
            "Graph node output belongs to another activity attempt",
            code="graph_physical_activity_superseded",
            details={"resource_ref": commit.resource_ref},
        )
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("resource_ref", resource.resource_ref, commit.resource_ref),
            (
                "output_keys",
                frozenset(execution_input.output_keys),
                frozenset(commit.candidate.output_refs),
            ),
        )
        if expected != actual
    )
    if mismatches:
        raise HarnessValidationError(
            "committed node output conflicts with the physical activity contract",
            code="graph_physical_activity_output_mismatch",
            details={"mismatches": list(mismatches)},
        )


def _failed_activity_result(
    activity: HarnessGraphActivity,
    attempt: HarnessGraphActivityOutputAttemptResult,
    worker_result: HarnessWorkerResult | None,
) -> HarnessGraphActivityResult:
    outcome = attempt.outcome
    if outcome.state is AttemptState.TIMED_OUT:
        status = HarnessGraphActivityResultStatus.TIMEOUT
    elif outcome.state is AttemptState.INDETERMINATE or outcome.indeterminate:
        status = HarnessGraphActivityResultStatus.INDETERMINATE
    else:
        status = HarnessGraphActivityResultStatus.FAILED
    context = outcome.context
    evidence_ref = canonical_checksum(
        {
            "schema_version": HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA,
            "activity_id": activity.activity_id,
            "activity_checksum": activity.activity_checksum,
            "physical_attempt_id": (
                None if context is None else context.attempt_id
            ),
            "attempt_state": outcome.state.value,
            "reason_code": outcome.reason_code,
            "error_type": (
                None if outcome.error is None else type(outcome.error).__name__
            ),
            "termination_confirmed": outcome.termination_confirmed,
            "indeterminate": outcome.indeterminate,
            "worker_result_ref": (
                None
                if worker_result is None
                else worker_result.candidate_result_ref
            ),
        }
    )
    payload_ref = (
        worker_result.candidate_result_ref
        if worker_result is not None
        else evidence_ref
    )
    return HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=evidence_ref,
        payload_ref=payload_ref,
        status=status,
        termination_confirmed=outcome.termination_confirmed,
    )


def _assert_result_matches_activity(
    result: HarnessGraphActivityResult,
    activity: HarnessGraphActivity,
) -> None:
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("activity_id", activity.activity_id, result.activity_id),
            ("node_instance_id", activity.node_instance_id, result.node_instance_id),
            ("attempt", activity.attempt, result.attempt),
            ("idempotency_key", activity.idempotency_key, result.idempotency_key),
            (
                "fencing_generation",
                activity.fencing_generation,
                result.fencing_generation,
            ),
            ("activity_ref", activity.activity_ref, result.activity_ref),
            ("tenant_scope_ref", activity.tenant_scope_ref, result.tenant_scope_ref),
            (
                "identity_scope_ref",
                activity.identity_scope_ref,
                result.identity_scope_ref,
            ),
            (
                "subject_scope_ref",
                activity.subject_scope_ref,
                result.subject_scope_ref,
            ),
        )
        if expected != actual
    )
    if mismatches:
        raise HarnessValidationError(
            "physical Graph result conflicts with its durable activity",
            code="graph_physical_activity_result_mismatch",
            details={"mismatches": list(mismatches)},
        )


def _output_keys(values: Any) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise HarnessValidationError(
            "Graph candidate activity requires declared output keys",
            code="graph_activity_execution_output_keys_invalid",
        )
    normalized = tuple(
        required_text(value, "activity_execution_input.output_key")
        for value in values
    )
    if not normalized or len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            "Graph candidate activity requires unique non-empty output keys",
            code="graph_activity_execution_output_keys_invalid",
        )
    return normalized


def _checksum(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="graph_activity_execution_reference_invalid",
        )
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="graph_activity_execution_reference_invalid",
        ) from exc
    return value


__all__ = [
    "HARNESS_GRAPH_ACTIVITY_EXECUTION_INPUT_SCHEMA",
    "HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA",
    "HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY",
    "HarnessGraphActivityExecutionCommitPort",
    "HarnessGraphActivityExecutionInput",
    "HarnessGraphActivityExecutionInputResolverPort",
    "HarnessGraphPhysicalActivityExecutionResult",
    "HarnessGraphPhysicalActivityExecutor",
]
