from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    HarnessAdmittedGraphActivityAttempt,
    HarnessCommittedNodeOutputReceipt,
    HarnessNodeOutputAttemptStatus,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputCommitGuard,
    HarnessNodeOutputLease,
    HarnessNodeOutputResourceIdentity,
    HarnessNodeOutputResourcePort,
)
from framework.harness.graph.definition import HarnessGraphDefinition
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
    """Admission-before-lease boundary for production Graph node output."""

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


class HarnessCommittedNodeOutputInputResolver:
    """Resolve Graph-declared committed-output receipt inputs."""

    def __init__(self, *, resource: HarnessNodeOutputResourcePort) -> None:
        if not isinstance(resource, HarnessNodeOutputResourcePort):
            raise TypeError("resource must implement HarnessNodeOutputResourcePort")
        self._resource = resource

    def resolve(
        self,
        *,
        definition: HarnessGraphDefinition,
        binding_id: str,
        producer_activity: HarnessGraphActivity,
        payload: Any,
    ) -> HarnessCommittedNodeOutputReceipt:
        if not isinstance(definition, HarnessGraphDefinition):
            raise TypeError("definition must be HarnessGraphDefinition")
        if not isinstance(producer_activity, HarnessGraphActivity):
            raise TypeError("producer_activity must be HarnessGraphActivity")
        binding = definition.committed_output_binding(binding_id)
        if binding is None:
            raise HarnessValidationError(
                "Graph has no declared committed node-output binding",
                code="graph_committed_node_output_binding_missing",
                details={"binding_id": str(binding_id)},
            )
        leaf = definition.leaf_activity_binding(binding.producer_activity_id)
        if (
            leaf is None
            or leaf.activity_ref != producer_activity.activity_ref
            or binding.producer_node_id != producer_activity.node_id
        ):
            raise HarnessValidationError(
                "committed node-output producer does not match its Graph binding",
                code="graph_committed_node_output_producer_mismatch",
                details={"binding_id": binding.binding_id},
            )
        self._assert_graph_identity(definition, producer_activity.graph_ref)
        resource = HarnessNodeOutputResourceIdentity.for_activity(producer_activity)
        commit = self._resource.committed_output(resource)
        if commit is None:
            raise HarnessValidationError(
                "committed node-output binding has no durable resource commit",
                code="graph_committed_node_output_missing",
                details={
                    "binding_id": binding.binding_id,
                    "resource_ref": resource.resource_ref,
                },
            )
        definition.verify_integrity()
        if definition.definition_checksum is None:  # pragma: no cover - invariant
            raise AssertionError("Graph definition checksum was not materialized")
        receipt = HarnessCommittedNodeOutputReceipt(
            graph_definition_checksum=definition.definition_checksum,
            binding_id=binding.binding_id,
            receipt_input_key=binding.receipt_input_key,
            producer_activity_id=binding.producer_activity_id,
            producer_activity_ref=leaf.activity_ref,
            resource=resource,
            commit=commit,
            output_key=binding.producer_output_key,
        )
        receipt.assert_matches_payload(payload)
        return receipt

    def verify(
        self,
        receipt: HarnessCommittedNodeOutputReceipt | Mapping[str, Any],
        *,
        definition: HarnessGraphDefinition,
        binding_id: str,
        payload: Any,
    ) -> HarnessCommittedNodeOutputReceipt:
        if not isinstance(definition, HarnessGraphDefinition):
            raise TypeError("definition must be HarnessGraphDefinition")
        if not isinstance(receipt, HarnessCommittedNodeOutputReceipt):
            if not isinstance(receipt, Mapping):
                raise TypeError(
                    "receipt must be HarnessCommittedNodeOutputReceipt or mapping"
                )
            receipt = HarnessCommittedNodeOutputReceipt.from_dict(receipt)
        binding = definition.committed_output_binding(binding_id)
        if binding is None:
            raise HarnessValidationError(
                "Graph has no declared committed node-output binding",
                code="graph_committed_node_output_binding_missing",
                details={"binding_id": str(binding_id)},
            )
        leaf = definition.leaf_activity_binding(binding.producer_activity_id)
        definition.verify_integrity()
        mismatches = tuple(
            field_name
            for field_name, expected, actual in (
                (
                    "graph_definition_checksum",
                    definition.definition_checksum,
                    receipt.graph_definition_checksum,
                ),
                ("binding_id", binding.binding_id, receipt.binding_id),
                (
                    "receipt_input_key",
                    binding.receipt_input_key,
                    receipt.receipt_input_key,
                ),
                (
                    "producer_activity_id",
                    binding.producer_activity_id,
                    receipt.producer_activity_id,
                ),
                (
                    "producer_activity_ref",
                    None if leaf is None else leaf.activity_ref,
                    receipt.producer_activity_ref,
                ),
                (
                    "producer_node_id",
                    binding.producer_node_id,
                    receipt.resource.node_id,
                ),
                (
                    "producer_output_key",
                    binding.producer_output_key,
                    receipt.output_key,
                ),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "committed node-output receipt does not match its Graph binding",
                code="graph_committed_node_output_binding_mismatch",
                details={"binding_id": binding.binding_id, "mismatches": mismatches},
            )
        self._assert_graph_identity(definition, receipt.resource.graph_ref)
        current = self._resource.committed_output(receipt.resource)
        if current != receipt.commit:
            raise HarnessValidationError(
                "committed node-output receipt is not the current resource commit",
                code="graph_committed_node_output_commit_mismatch",
                details={
                    "binding_id": binding.binding_id,
                    "resource_ref": receipt.resource.resource_ref,
                },
            )
        receipt.assert_matches_payload(payload)
        return receipt

    @staticmethod
    def _assert_graph_identity(
        definition: HarnessGraphDefinition,
        graph_ref: HarnessGraphReference,
    ) -> None:
        if (
            graph_ref.graph_id != definition.graph_id
            or graph_ref.identity_version != definition.graph_version
        ):
            raise HarnessValidationError(
                "committed node-output resource is outside its Graph definition",
                code="graph_committed_node_output_graph_mismatch",
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
    "HarnessCommittedNodeOutputInputResolver",
    "HarnessGraphActivityOutputAttemptResult",
]
