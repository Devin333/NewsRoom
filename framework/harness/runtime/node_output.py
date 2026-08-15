from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.node_output import (
    HarnessAdmittedGraphActivityAttempt,
    HarnessNodeOutputAttemptStatus,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputCommitGuard,
    HarnessNodeOutputLease,
    HarnessNodeOutputResourceIdentity,
    HarnessNodeOutputResourcePort,
)
from framework.shared.attempts import (
    AttemptContext,
    AttemptFinalization,
    AttemptIdentity,
    AttemptLifecycleSink,
    AttemptOutcome,
    AttemptState,
    AttemptSupervisor,
    DeadlineAdmissionPolicy,
    ExecutionLimits,
    LocalRetryBudget,
    RetryCreditLedger,
)
from framework.shared.time import utc_now


@dataclass(frozen=True, slots=True)
class HarnessGraphActivityOutputAttemptResult:
    outcome: AttemptOutcome[HarnessNodeOutputCandidate]
    admission: HarnessAdmittedGraphActivityAttempt | None
    lease: HarnessNodeOutputLease | None
    commit: HarnessNodeOutputCommit | None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, AttemptOutcome):
            raise TypeError("outcome must be AttemptOutcome")
        if (self.admission is None) != (self.lease is None):
            raise HarnessValidationError(
                "node-output admission and lease must be present together",
                code="graph_node_output_attempt_result_invalid",
            )
        if not self.outcome.started:
            if self.admission is not None or self.commit is not None:
                raise HarnessValidationError(
                    "rejected activity attempt cannot own or commit node output",
                    code="graph_node_output_attempt_result_invalid",
                )
        if self.commit is not None:
            if self.lease is None or not self.outcome.succeeded:
                raise HarnessValidationError(
                    "node-output commit requires one successful admitted attempt",
                    code="graph_node_output_attempt_result_invalid",
                )
            if (
                self.commit.lease_ref != self.lease.lease_ref
                or self.commit.owner_attempt_id != self.lease.owner_attempt_id
                or self.commit.generation != self.lease.generation
            ):
                raise HarnessValidationError(
                    "node-output commit conflicts with its activity attempt lease",
                    code="graph_node_output_attempt_result_invalid",
                )


class HarnessAdmittedGraphActivityOutputAdapter:
    """Inactive adapter proving admission-before-lease ordering for Graph output.

    The adapter is intentionally not a ``HarnessGraphActivityDispatcherPort`` and
    is not installed by production composition. Gate B must provide the durable
    resource binding and explicitly connect the live activity executor.
    """

    def __init__(
        self,
        *,
        resource: HarnessNodeOutputResourcePort,
        supervisor: AttemptSupervisor,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(resource, HarnessNodeOutputResourcePort):
            raise TypeError("resource must implement HarnessNodeOutputResourcePort")
        if not isinstance(supervisor, AttemptSupervisor):
            raise TypeError("supervisor must be AttemptSupervisor")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._resource = resource
        self._supervisor = supervisor
        self._clock = clock

    def run(
        self,
        fn: Callable[[], HarnessNodeOutputCandidate],
        *,
        activity: HarnessGraphActivity,
        timeout_seconds: float | None,
        operation_id: str | None = None,
        attempt_id: str | None = None,
        local_budget: LocalRetryBudget | None = None,
        retry_ledger: RetryCreditLedger | None = None,
        admission_policy: DeadlineAdmissionPolicy | None = None,
        execution_limits: ExecutionLimits | None = None,
        parent_context: AttemptContext | None = None,
        cancel_event: threading.Event | None = None,
        parent_cancel_event: threading.Event | None = None,
        event_sink: AttemptLifecycleSink | None = None,
    ) -> HarnessGraphActivityOutputAttemptResult:
        if not callable(fn):
            raise TypeError("fn must be callable")
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        resource_identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
        admission_holder: dict[str, HarnessAdmittedGraphActivityAttempt] = {}
        lease_holder: dict[str, HarnessNodeOutputLease] = {}
        commit_holder: dict[str, HarnessNodeOutputCommit] = {}
        finalization_state = {"prepared_for_commit": False, "handled": False}

        def prepare(identity: AttemptIdentity) -> Callable[[], None]:
            admission = HarnessAdmittedGraphActivityAttempt(
                activity_id=activity.activity_id,
                activity_checksum=activity.activity_checksum,
                owner_attempt_id=identity.attempt_id,
                operation_id=identity.operation_id,
                operation_kind=identity.operation_kind,
                idempotency_key=identity.idempotency_key,
                local_attempt_no=identity.local_attempt_no,
                parent_attempt_id=identity.parent_attempt_id,
                retry_credit_id=identity.retry_credit_id,
                admitted_at=self._clock(),
            )
            lease = self._resource.acquire_after_admission(activity, admission)
            admission_holder["value"] = admission
            lease_holder["value"] = lease

            def cleanup() -> None:
                if (
                    not finalization_state["prepared_for_commit"]
                    and not finalization_state["handled"]
                ):
                    self._resource.revoke(lease)
                    finalization_state["handled"] = True

            return cleanup

        def finalize(
            outcome: AttemptOutcome[HarnessNodeOutputCandidate],
        ) -> (
            AttemptOutcome[HarnessNodeOutputCandidate]
            | AttemptFinalization[HarnessNodeOutputCandidate]
        ):
            lease = lease_holder.get("value")
            if lease is None:
                raise HarnessValidationError(
                    "started Graph activity attempt is missing its node-output lease",
                    code="graph_node_output_lease_missing",
                )
            if not _normal_output_allowed(outcome):
                self._resource.revoke(lease)
                finalization_state["handled"] = True
                return outcome
            candidate = outcome.value
            if not isinstance(candidate, HarnessNodeOutputCandidate):
                self._resource.revoke(lease)
                finalization_state["handled"] = True
                raise HarnessValidationError(
                    "successful Graph activity must return a node-output candidate",
                    code="graph_node_output_candidate_missing",
                )
            staged = self._resource.stage(
                lease,
                candidate,
                staged_at=self._clock(),
            )
            finalization_state["prepared_for_commit"] = True
            guard = HarnessNodeOutputCommitGuard(
                attempt_status=HarnessNodeOutputAttemptStatus.SUCCEEDED,
                termination_confirmed=outcome.termination_confirmed,
                descendants_determinate=not outcome.indeterminate,
            )

            def rollback() -> None:
                self._resource.discard(staged)
                self._resource.revoke(lease)
                finalization_state["handled"] = True

            def complete() -> None:
                try:
                    commit_holder["value"] = self._resource.commit(
                        staged,
                        guard,
                        committed_at=self._clock(),
                    )
                except BaseException:
                    self._resource.discard(staged)
                    self._resource.revoke(lease)
                    raise
                finally:
                    finalization_state["handled"] = True

            return AttemptFinalization(
                outcome=outcome,
                rollback=rollback,
                complete=complete,
            )

        outcome = self._supervisor.run(
            fn,
            timeout_seconds=timeout_seconds,
            idempotency_key=activity.idempotency_key,
            operation_id=(
                operation_id
                or (
                    "graph-activity://"
                    f"{activity.run_id}/{activity.node_instance_id}"
                )
            ),
            operation_kind="graph_activity",
            attempt_id=attempt_id,
            local_budget=local_budget,
            retry_ledger=retry_ledger,
            admission_policy=admission_policy,
            execution_limits=execution_limits,
            cancel_event=cancel_event,
            parent_cancel_event=parent_cancel_event,
            parent_context=parent_context,
            prepare=prepare,
            finalize=finalize,
            event_sink=event_sink,
        )
        commit = commit_holder.get("value")
        if commit is not None and self._resource.committed_output(resource_identity) != commit:
            raise HarnessValidationError(
                "node-output resource did not retain its committed output",
                code="graph_node_output_commit_missing",
            )
        return HarnessGraphActivityOutputAttemptResult(
            outcome=outcome,
            admission=admission_holder.get("value"),
            lease=lease_holder.get("value"),
            commit=commit,
        )


def _normal_output_allowed(
    outcome: AttemptOutcome[HarnessNodeOutputCandidate],
) -> bool:
    context = outcome.context
    return bool(
        outcome.state is AttemptState.SUCCEEDED
        and outcome.termination_confirmed
        and not outcome.indeterminate
        and context is not None
        and not context.has_indeterminate_descendant
        and not context.has_unconfirmed_descendant
    )


__all__ = [
    "HarnessAdmittedGraphActivityOutputAdapter",
    "HarnessGraphActivityOutputAttemptResult",
]
