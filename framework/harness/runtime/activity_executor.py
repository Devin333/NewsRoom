from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.harness.control_plane.activity_execution import (
    HARNESS_GRAPH_ACTIVITY_FAILURE_EVIDENCE_SCHEMA,
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
    HarnessGraphActivityExecutionCommitPort,
    HarnessGraphActivityExecutionInput,
    HarnessGraphActivityExecutionInputResolverPort,
    HarnessGraphActivityTaskContext,
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
from framework.harness.graph.bindings import (
    HarnessActivityUsage,
    HarnessRuntimeBindingAuthority,
)
from framework.harness.graph.canonical import (
    canonical_checksum,
    mapping_to_dict,
    required_text,
)
from framework.harness.graph.output_projection import (
    project_graph_worker_outputs,
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
                or self.worker_result is None
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
    """Graph-native physical dispatcher for candidate-only leaves.

    The executor consumes a durable ``HarnessGraphActivity`` and never invokes
    ``HarnessActivityContractBinding.implementation.dispatch``. Exact pair and
    capability admission remain composition-owned through the runtime binding
    authority. Production composition must provide durable input, node-output,
    and result ports before installing this executor.
    """

    def __init__(
        self,
        *,
        binding_authority: HarnessRuntimeBindingAuthority,
        input_resolver: HarnessGraphActivityExecutionInputResolverPort,
        node_output_resource: HarnessNodeOutputResourcePort,
        result_committer: HarnessGraphActivityExecutionCommitPort | None,
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
        if result_committer is not None and not isinstance(
            result_committer, HarnessGraphActivityExecutionCommitPort
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
        self._result_committer_bound = False
        self._output_adapter = HarnessAdmittedGraphActivityOutputAdapter(
            resource=node_output_resource,
            supervisor=supervisor,
            clock=clock,
        )

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        """Execute one already committed Graph activity descriptor."""

        self.execute(activity)

    def bind_result_committer(
        self,
        result_committer: HarnessGraphActivityExecutionCommitPort,
    ) -> None:
        """Bind the composition-owned durable result sink exactly once."""

        if not isinstance(
            result_committer,
            HarnessGraphActivityExecutionCommitPort,
        ):
            raise TypeError(
                "result_committer must implement "
                "HarnessGraphActivityExecutionCommitPort"
            )
        if (
            self._result_committer is not result_committer
            and getattr(self, "_result_committer_bound", False)
        ):
            raise HarnessValidationError(
                "Graph physical executor result committer is immutable",
                code="graph_result_committer_rebind_forbidden",
            )
        self._result_committer = result_committer
        self._result_committer_bound = True

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

        compensation_handler = None
        compensation = execution_input.task.get("compensation")
        if execution_input.required_usage is HarnessActivityUsage.COMPENSATION:
            handler_ref = _validate_compensation_task(
                compensation,
                activity=activity,
            )
            compensation_handler = self._binding_authority.resolve_compensation(
                handler_ref
            ).implementation
        elif compensation is not None:
            raise HarnessValidationError(
                "compensation payload requires compensation activity usage",
                code="graph_compensation_usage_mismatch",
            )

        resource_identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
        existing = self._node_output_resource.committed_output(resource_identity)
        if existing is not None and existing.activity_id == activity.activity_id:
            return self._recover_committed_output(
                activity,
                execution_input,
                existing,
            )

        worker_holder: dict[str, HarnessWorkerResult] = {}

        def invoke() -> HarnessNodeOutputCandidate:
            physical_task = _worker_task(execution_input, activity)
            if compensation_handler is None:
                worker_result = _coerce_worker_result(
                    binding.worker.implementation.execute(physical_task)
                )
            else:
                worker_result = _coerce_compensation_result(
                    compensation_handler.compensate(physical_task)
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
        if (
            worker_result is None
            and attempt.outcome.started
            and attempt.outcome.error is not None
        ):
            # A worker may fail before returning a typed candidate (for
            # example, a provider authorization/context guard). Preserve that
            # deterministic failure as the Graph result evidence instead of
            # losing the original error behind a missing-result exception.
            worker_result = HarnessWorkerResult(
                status=HarnessWorkerStatus.FAILED,
                error=str(attempt.outcome.error),
            )
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

    def recover_committed_output(
        self,
        activity: HarnessGraphActivity,
        *,
        execution_input: HarnessGraphActivityExecutionInput | None = None,
    ) -> HarnessGraphPhysicalActivityExecutionResult:
        """Recover only the exact current durable node-output commit.

        Recovery is deliberately separate from :meth:`execute`: a durable
        Worker result or candidate reference is not sufficient evidence to
        reconstruct a Graph result.  The resource is the authority for the
        current fenced output slot, and the normal result committer still
        records the idempotent Graph result projection.
        """

        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if execution_input is None:
            execution_input = self._input_resolver.resolve_execution_input(activity)
        if not isinstance(execution_input, HarnessGraphActivityExecutionInput):
            raise HarnessValidationError(
                "Graph activity input resolver returned an invalid contract",
                code="graph_activity_execution_input_invalid",
            )
        execution_input.assert_matches(activity)
        resource_identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
        commit = self._node_output_resource.committed_output(resource_identity)
        if commit is None:
            raise HarnessValidationError(
                "Graph result recovery requires the current durable node-output commit",
                code="graph_physical_result_commit_missing",
                details={"resource_ref": resource_identity.resource_ref},
            )
        return self._recover_committed_output(
            activity,
            execution_input,
            commit,
        )

    def _recover_committed_output(
        self,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        commit: HarnessNodeOutputCommit,
    ) -> HarnessGraphPhysicalActivityExecutionResult:
        _assert_output_commit_matches(activity, execution_input, commit)
        payload = commit.candidate.worker_result
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "committed Graph node output lacks durable Worker evidence",
                code="graph_physical_result_worker_evidence_missing",
            )
        worker_result = HarnessWorkerResult.from_dict(payload)
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
            attempt=None,
            worker_result=worker_result,
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
        if self._result_committer is None:
            raise HarnessValidationError(
                "Graph physical executor has no durable result committer",
                code="graph_result_committer_missing",
            )
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
    task = mapping_to_dict(execution_input.task)
    compensation = task.get("compensation")
    if isinstance(compensation, Mapping):
        # Compensation handlers receive the durable entry identity as part of
        # their physical request.  The typed Graph activity context remains the
        # sole Harness-owned activity descriptor; no legacy ``harness_activity``
        # alias is ever injected.
        task.update(dict(compensation))
        task["attempt"] = activity.attempt
        task["fencing_generation"] = activity.fencing_generation
    return {
        **task,
        HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY: (
            HarnessGraphActivityTaskContext.for_execution_input(
                activity,
                execution_input,
            ).to_dict()
        ),
    }


def _validate_compensation_task(
    value: Any,
    *,
    activity: HarnessGraphActivity,
) -> str:
    expected_fields = {
        "binding_id",
        "entry_id",
        "origin_node_instance_id",
        "effect_outcome_ref",
        "effect_commit_sequence",
        "handler_ref",
        "activity_ref",
        "idempotency_key",
        "tenant_scope_ref",
        "identity_scope_ref",
        "subject_scope_ref",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise HarnessValidationError(
            "compensation execution requires its exact binding payload",
            code="graph_compensation_binding_invalid",
            details={
                "missing": sorted(expected_fields.difference(value or {}))
                if isinstance(value, Mapping)
                else sorted(expected_fields),
                "unknown": sorted(set(value).difference(expected_fields))
                if isinstance(value, Mapping)
                else [],
            },
        )
    required_text(value["binding_id"], "compensation.binding_id")
    _checksum(value["entry_id"], "compensation.entry_id")
    required_text(
        value["origin_node_instance_id"],
        "compensation.origin_node_instance_id",
    )
    _checksum(value["effect_outcome_ref"], "compensation.effect_outcome_ref")
    effect_commit_sequence = value["effect_commit_sequence"]
    if (
        isinstance(effect_commit_sequence, bool)
        or not isinstance(effect_commit_sequence, int)
        or effect_commit_sequence < 1
    ):
        raise HarnessValidationError(
            "compensation effect commit sequence must be positive",
            code="graph_compensation_binding_invalid",
        )
    handler_ref = required_text(
        value["handler_ref"],
        "compensation.handler_ref",
    )
    activity_ref = required_text(
        value["activity_ref"],
        "compensation.activity_ref",
    )
    if activity_ref != activity.activity_ref.exact_ref:
        raise HarnessValidationError(
            "compensation task activity reference conflicts with its Graph activity",
            code="graph_compensation_activity_reference_mismatch",
            details={
                "expected": activity.activity_ref.exact_ref,
                "actual": activity_ref,
            },
        )
    _checksum(value["idempotency_key"], "compensation.idempotency_key")
    scope_mismatches = tuple(
        field_name
        for field_name in (
            "tenant_scope_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        )
        if value[field_name] != getattr(activity, field_name)
    )
    if scope_mismatches:
        raise HarnessValidationError(
            "compensation task scope conflicts with its Graph activity",
            code="graph_compensation_scope_mismatch",
            details={"mismatches": list(scope_mismatches)},
        )
    return handler_ref


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


def _coerce_compensation_result(value: Any) -> HarnessWorkerResult:
    """Normalize an exact compensation handler result at the worker boundary."""

    to_dict = getattr(value, "to_dict", None)
    payload = to_dict() if callable(to_dict) else value
    if isinstance(payload, Mapping) and "status" not in payload:
        result = HarnessWorkerResult(
            HarnessWorkerStatus.SUCCEEDED,
            output=dict(payload),
        )
    else:
        result = _coerce_worker_result(payload)
    if result.effect_intent is not None:
        raise HarnessValidationError(
            "compensation handler cannot emit a forward side-effect intent",
            code="compensation_side_effect_intent_rejected",
        )
    return result


def _node_output_candidate(
    execution_input: HarnessGraphActivityExecutionInput,
    worker_result: HarnessWorkerResult,
) -> HarnessNodeOutputCandidate:
    output_keys = tuple(execution_input.output_keys)
    projected_outputs = project_graph_worker_outputs(
        worker_result.output,
        output_keys,
    )
    if projected_outputs is None:
        raise HarnessValidationError(
            "Graph worker outputs do not match the physical activity contract",
            code="graph_activity_worker_output_mismatch",
            details={
                "expected_output_keys": sorted(output_keys),
                "actual_output_keys": sorted(worker_result.output),
            },
        )
    output_refs = {
        output_key: canonical_checksum(value)
        for output_key, value in projected_outputs.items()
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
        worker_result=worker_result.to_dict(),
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
    "HarnessGraphPhysicalActivityExecutionResult",
    "HarnessGraphPhysicalActivityExecutor",
]
