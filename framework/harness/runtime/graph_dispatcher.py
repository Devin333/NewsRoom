from __future__ import annotations

"""The single physical execution boundary for live Graph activities.

The control plane owns durable decisions and projections.  This adapter owns
the worker call, attempt admission, node-output fencing, and result evidence.
It deliberately receives narrow callbacks instead of a control-plane object so
that it cannot select routes or mutate Graph state on its own.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import threading
from threading import Lock
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityExecutionCommitPort,
    HarnessGraphActivityExecutionInput,
    HarnessGraphActivityExecutionInputResolverPort,
)
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultStatus,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphActivityCancellationRequest,
)
from framework.harness.control_plane.graph_state import HarnessGraphState
from framework.harness.graph.model import NormalizedHarnessGraph
from framework.harness.runtime.activity_executor import (
    HarnessGraphPhysicalActivityExecutionResult,
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.workers.result import (
    HarnessWorkerEvidence,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)


GraphActivityAccept = Callable[
    [HarnessGraphActivity, HarnessGraphActivityExecutionInput],
    HarnessWorkerResult | None,
]
GraphActivityCallMarker = Callable[
    [HarnessGraphActivity, HarnessGraphActivityExecutionInput],
    None,
]
GraphActivityResultRecord = Callable[
    [
        HarnessGraphActivity,
        NormalizedHarnessGraph,
        HarnessWorkerResult,
    ],
    HarnessEvent,
]
GraphActivityResultApply = Callable[
    [HarnessGraphActivity, HarnessWorkerResult, HarnessGraphActivityResult],
    HarnessGraphState,
]


class _InputResolver(HarnessGraphActivityExecutionInputResolverPort):
    def __init__(
        self,
        resolver: Callable[[HarnessGraphActivity], HarnessGraphActivityExecutionInput],
    ) -> None:
        self._resolver = resolver

    def resolve_execution_input(
        self,
        activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        return self._resolver(activity)


@dataclass(slots=True)
class _ActiveGraphCancellation:
    activity: HarnessGraphActivity
    cancel_event: threading.Event


@dataclass(slots=True)
class _ResultCommitter:
    graph_resolver: Callable[[HarnessGraphActivity], NormalizedHarnessGraph]
    record: GraphActivityResultRecord
    events: dict[str, HarnessEvent]
    lock: Lock

    def commit_execution_result(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        worker_result: HarnessWorkerResult | None,
        node_output_commit: Any,
        result: HarnessGraphActivityResult,
    ) -> HarnessGraphActivityResult:
        del execution_input
        if worker_result is None:
            candidate = getattr(node_output_commit, "candidate", None)
            payload = getattr(candidate, "worker_result", None)
            if isinstance(payload, Mapping):
                worker_result = HarnessWorkerResult.from_dict(payload)
            elif result.status is not HarnessGraphActivityResultStatus.SUCCEEDED:
                # A started terminal failure is authoritative even when the
                # worker never returned a candidate. Preserve the Graph result
                # identity as typed Worker evidence for durable replay.
                worker_result = _terminal_worker_result_for_graph_result(
                    activity,
                    result,
                )
            else:
                raise HarnessValidationError(
                    "physical Graph recovery requires embedded Worker evidence",
                    code="graph_physical_result_worker_evidence_missing",
                )
        event = self.record(
            activity,
            self.graph_resolver(activity),
            worker_result,
        )
        if not isinstance(event, HarnessEvent):
            raise HarnessValidationError(
                "Graph result record callback returned an invalid event",
                code="graph_result_event_invalid",
            )
        with self.lock:
            existing = self.events.get(activity.activity_id)
            if existing is not None and existing.event_id != event.event_id:
                raise HarnessValidationError(
                    "Graph activity resolved conflicting result events",
                    code="graph_result_event_conflict",
                )
            self.events[activity.activity_id] = event
        return result


class HarnessGraphPhysicalActivityDispatcher:
    """Dispatch Graph activities through one physical executor instance."""

    def __init__(
        self,
        *,
        executor: HarnessGraphPhysicalActivityExecutor,
        graph_resolver: Callable[[HarnessGraphActivity], NormalizedHarnessGraph],
        input_resolver: HarnessGraphActivityExecutionInputResolverPort | Callable[
            [HarnessGraphActivity], HarnessGraphActivityExecutionInput
        ],
        accept: GraphActivityAccept,
        record_call_marker: GraphActivityCallMarker,
        record_result: GraphActivityResultRecord,
        apply_result: GraphActivityResultApply,
        capabilities_resolver: Callable[[Any], Any] | None = None,
        durable_recovery_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(executor, HarnessGraphPhysicalActivityExecutor):
            raise TypeError("executor must be HarnessGraphPhysicalActivityExecutor")
        if not isinstance(input_resolver, HarnessGraphActivityExecutionInputResolverPort):
            if not callable(input_resolver):
                raise TypeError("input_resolver must implement its Graph protocol")
            input_resolver = _InputResolver(input_resolver)
        for callback, name in (
            (graph_resolver, "graph_resolver"),
            (accept, "accept"),
            (record_call_marker, "record_call_marker"),
            (record_result, "record_result"),
            (apply_result, "apply_result"),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if durable_recovery_resolver is not None and not callable(
            durable_recovery_resolver
        ):
            raise TypeError("durable_recovery_resolver must be callable")
        self._executor = executor
        self._graph_resolver = graph_resolver
        self._input_resolver = input_resolver
        self._accept = accept
        self._record_call_marker = record_call_marker
        self._record_result = record_result
        self._apply_result = apply_result
        self._capabilities_resolver = capabilities_resolver
        self._durable_recovery_resolver = durable_recovery_resolver
        self._events: dict[str, HarnessEvent] = {}
        self._lock = Lock()
        self._active_cancellations: dict[str, _ActiveGraphCancellation] = {}
        self._indeterminate_activities: dict[str, HarnessGraphActivity] = {}
        self._pending_cancellations: dict[
            str,
            HarnessGraphActivityCancellationRequest,
        ] = {}
        self._cancellation_requests: dict[
            str,
            HarnessGraphActivityCancellationRequest,
        ] = {}
        self._result_committer = _ResultCommitter(
            graph_resolver=graph_resolver,
            record=record_result,
            events=self._events,
            lock=self._lock,
        )
        executor.bind_result_committer(self._result_committer)

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        cancel_event = self._begin_cancellation(activity)
        try:
            graph = self._graph_resolver(activity)
            if not isinstance(graph, NormalizedHarnessGraph):
                raise TypeError("graph_resolver must return NormalizedHarnessGraph")
            execution_input = self._input_resolver.resolve_execution_input(activity)
            if not isinstance(
                execution_input,
                HarnessGraphActivityExecutionInput,
            ):
                raise HarnessValidationError(
                    "Graph input resolver returned an invalid execution input",
                    code="graph_activity_execution_input_invalid",
                )
            execution_input.assert_matches(activity)

            existing = self._accept(activity, execution_input)
            if existing is not None:
                if not isinstance(existing, HarnessWorkerResult):
                    raise HarnessValidationError(
                        "Graph accept callback returned an invalid Worker result",
                        code="graph_activity_worker_result_invalid",
                    )
                if existing.status is HarnessWorkerStatus.SUCCEEDED:
                    recovered = self._executor.recover_committed_output(
                        activity,
                        execution_input=execution_input,
                    )
                    if (
                        recovered.worker_result is None
                        or recovered.node_output_commit is None
                        or recovered.graph_result is None
                    ):
                        raise HarnessValidationError(
                            "Graph result recovery returned an incomplete durable receipt",
                            code="graph_physical_result_recovery_invalid",
                        )
                    if recovered.worker_result.to_dict() != existing.to_dict():
                        raise HarnessValidationError(
                            "durable node-output Worker evidence conflicts with recorded Graph result",
                            code="graph_physical_result_worker_evidence_conflict",
                        )
                    self._apply_result(
                        activity,
                        recovered.worker_result,
                        recovered.graph_result,
                    )
                else:
                    # Failure/blocked outcomes do not publish normal node
                    # output.  Their recorded Worker evidence remains the
                    # terminal failure fact and is safe to re-apply.
                    result_event = self._record_result(activity, graph, existing)
                    if not isinstance(result_event, HarnessEvent):
                        raise HarnessValidationError(
                            "Graph result record callback returned an invalid event",
                            code="graph_result_event_invalid",
                        )
                    graph_result = _recovered_graph_result(
                        activity,
                        existing,
                        result_event,
                    )
                    self._apply_result(activity, existing, graph_result)
                return

            self._record_call_marker(activity, execution_input)
            physical = self._executor.execute(
                activity,
                cancel_event=cancel_event,
                # The executor owns retries and node-output fencing.  Graph-level
                # retry decisions remain outside this boundary.
            )
            if not isinstance(physical, HarnessGraphPhysicalActivityExecutionResult):
                raise HarnessValidationError(
                    "physical Graph executor returned an invalid execution result",
                    code="graph_physical_execution_result_invalid",
                )
            if physical.graph_result is None:
                raise HarnessValidationError(
                    "physical Graph execution produced no durable result",
                    code="graph_physical_execution_result_missing",
                )
            worker_result = physical.worker_result
            if worker_result is None:
                commit = physical.node_output_commit
                payload = (
                    None
                    if commit is None
                    else commit.candidate.worker_result
                )
                if isinstance(payload, Mapping):
                    worker_result = HarnessWorkerResult.from_dict(payload)
                elif physical.graph_result.status is not HarnessGraphActivityResultStatus.SUCCEEDED:
                    worker_result = _terminal_worker_result_for_graph_result(
                        activity,
                        physical.graph_result,
                    )
                else:
                    raise HarnessValidationError(
                        "physical Graph recovery lost its durable Worker evidence",
                        code="graph_physical_worker_result_missing",
                    )
            with self._lock:
                if physical.graph_result.termination_confirmed:
                    self._indeterminate_activities.pop(activity.activity_id, None)
                else:
                    # Preserve a process-local quarantine even if the durable
                    # result projection fails after physical execution. A
                    # recovery loop must never turn termination uncertainty
                    # into an automatic second invocation.
                    self._indeterminate_activities[activity.activity_id] = activity
            self._apply_result(activity, worker_result, physical.graph_result)
        finally:
            self._finish_cancellation(activity, cancel_event)

    def concurrency_capabilities_for(self, activity_ref: Any) -> Any:
        """The physical executor resolves exact capabilities at execution time.

        Parallel admission is pinned by the control plane before dispatch; this
        adapter intentionally has no second registry.  The callback is filled
        by composition when a dispatcher is used for parallel graphs.
        """

        if self._capabilities_resolver is None:
            return None
        return self._capabilities_resolver(activity_ref)

    def is_dispatching(self, activity_id: str) -> bool:
        """Report whether an activity is currently owned by this dispatcher.

        Recovery uses this narrow observation to avoid a second physical call
        while the original call is still in flight.  A durable dispatched
        marker alone is intentionally not treated as proof of completion.
        """

        if not isinstance(activity_id, str) or not activity_id.strip():
            raise ValueError("activity_id must be non-blank")
        with self._lock:
            return activity_id in self._active_cancellations

    def reconcile(self, activity: HarnessGraphActivity) -> bool:
        """Authorize one recovery dispatch when no local call owns activity."""

        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        with self._lock:
            uncertain = self._indeterminate_activities.get(activity.activity_id)
            if uncertain is not None:
                if uncertain != activity:
                    raise HarnessValidationError(
                        "Graph activity identity conflicts with its indeterminate quarantine",
                        code="graph_activity_indeterminate_conflict",
                        details={"activity_id": activity.activity_id},
                    )
                return False
            if activity.activity_id in self._active_cancellations:
                return False

        # A worker-call marker is durable ownership evidence, not completion
        # evidence.  After a process restart the local quarantine is gone, so
        # consult the transition store before authorizing another invocation.
        # The fail-closed result is intentional: an unresolved marker requires
        # explicit operator repair rather than an automatic duplicate call.
        resolver = self._durable_recovery_resolver
        if resolver is None:
            return True
        recovery = resolver(activity.run_id)
        if recovery is None:
            raise HarnessValidationError(
                "Graph recovery resolver returned no durable recovery",
                code="graph_activity_recovery_invalid",
                details={"run_id": activity.run_id},
            )
        recovery_run_id = getattr(recovery, "run_id", activity.run_id)
        if recovery_run_id != activity.run_id:
            raise HarnessValidationError(
                "Graph recovery resolver returned another run",
                code="graph_activity_recovery_invalid",
                details={
                    "run_id": activity.run_id,
                    "recovery_run_id": recovery_run_id,
                },
            )
        result_ids = {
            item.result.activity_id
            for item in getattr(recovery, "activity_result_commits", ())
            if getattr(item, "result", None) is not None
        }
        if activity.activity_id in result_ids:
            return True
        dispatched_ids = set(
            getattr(recovery, "dispatched_activity_ids", ()) or ()
        )
        return activity.activity_id not in dispatched_ids

    def request_cancellation(self, request: Any) -> None:
        if not isinstance(request, HarnessGraphActivityCancellationRequest):
            raise HarnessValidationError(
                "Graph cancellation request has an invalid type",
                code="graph_cancellation_request_invalid",
            )
        with self._lock:
            previous = self._cancellation_requests.get(request.activity_id)
            if previous is not None:
                if previous != request:
                    raise HarnessValidationError(
                        "Graph activity cancellation identity resolves conflicting requests",
                        code="graph_cancellation_request_conflict",
                        details={"activity_id": request.activity_id},
                    )
                return

            active = self._active_cancellations.get(request.activity_id)
            if active is None:
                self._pending_cancellations[request.activity_id] = request
            else:
                _assert_cancellation_matches_activity(request, active.activity)
                active.cancel_event.set()
            self._cancellation_requests[request.activity_id] = request

    def _begin_cancellation(self, activity: HarnessGraphActivity) -> threading.Event:
        event = threading.Event()
        with self._lock:
            existing = self._active_cancellations.get(activity.activity_id)
            if existing is not None:
                if existing.activity != activity:
                    raise HarnessValidationError(
                        "Graph activity identity resolves conflicting in-flight descriptors",
                        code="graph_activity_in_flight_conflict",
                    )
                raise HarnessValidationError(
                    "Graph activity is already being physically dispatched",
                    code="graph_activity_dispatch_in_flight",
                    details={"activity_id": activity.activity_id},
                )
            pending = self._pending_cancellations.pop(activity.activity_id, None)
            if pending is not None:
                _assert_cancellation_matches_activity(pending, activity)
                event.set()
            self._active_cancellations[activity.activity_id] = (
                _ActiveGraphCancellation(activity=activity, cancel_event=event)
            )
        return event

    def _finish_cancellation(
        self,
        activity: HarnessGraphActivity,
        event: threading.Event,
    ) -> None:
        with self._lock:
            active = self._active_cancellations.get(activity.activity_id)
            if active is not None and active.cancel_event is event:
                self._active_cancellations.pop(activity.activity_id, None)


def _assert_cancellation_matches_activity(
    request: HarnessGraphActivityCancellationRequest,
    activity: HarnessGraphActivity,
) -> None:
    mismatches = tuple(
        field_name
        for field_name, expected, actual in (
            ("run_id", activity.run_id, request.run_id),
            ("activity_id", activity.activity_id, request.activity_id),
            ("node_instance_id", activity.node_instance_id, request.node_instance_id),
            ("attempt", activity.attempt, request.attempt),
            ("idempotency_key", activity.idempotency_key, request.idempotency_key),
            (
                "fencing_generation",
                activity.fencing_generation,
                request.fencing_generation,
            ),
        )
        if expected != actual
    )
    if mismatches:
        raise HarnessValidationError(
            "Graph cancellation request does not match its activity descriptor",
            code="graph_cancellation_activity_mismatch",
            details={"mismatches": list(mismatches)},
        )


def _recovered_graph_result(
    activity: HarnessGraphActivity,
    worker_result: HarnessWorkerResult,
    event: HarnessEvent,
) -> HarnessGraphActivityResult:
    from framework.events.canonical import checksum_for

    terminal = worker_result.diagnostics.get("graph_activity_terminal")
    if isinstance(terminal, Mapping):
        raw_status = terminal.get("graph_result_status")
        try:
            status = HarnessGraphActivityResultStatus(raw_status)
        except (TypeError, ValueError):
            status = (
                HarnessGraphActivityResultStatus.SUCCEEDED
                if worker_result.status is HarnessWorkerStatus.SUCCEEDED
                else HarnessGraphActivityResultStatus.FAILED
            )
        termination_confirmed = terminal.get("termination_confirmed")
        if not isinstance(termination_confirmed, bool):
            termination_confirmed = status is HarnessGraphActivityResultStatus.SUCCEEDED
    else:
        status = (
            HarnessGraphActivityResultStatus.SUCCEEDED
            if worker_result.status is HarnessWorkerStatus.SUCCEEDED
            else HarnessGraphActivityResultStatus.FAILED
        )
        termination_confirmed = True

    return HarnessGraphActivityResult.for_activity(
        activity,
        evidence_ref=checksum_for(
            {
                "activity_id": activity.activity_id,
                "result_event_id": event.event_id,
                "payload_ref": worker_result.candidate_result_ref,
            }
        ),
        payload_ref=worker_result.candidate_result_ref,
        status=status,
        termination_confirmed=termination_confirmed,
    )


def _terminal_worker_result_for_graph_result(
    activity: HarnessGraphActivity,
    result: HarnessGraphActivityResult,
) -> HarnessWorkerResult:
    """Preserve a terminal Graph fact when no worker candidate exists."""

    if result.activity_id != activity.activity_id:
        raise HarnessValidationError(
            "terminal Graph result does not belong to its activity",
            code="graph_physical_activity_result_invalid",
        )
    status = result.status
    reason_code = {
        HarnessGraphActivityResultStatus.CANCELLED: "activity_cancelled",
        HarnessGraphActivityResultStatus.TIMEOUT: "activity_timeout",
        HarnessGraphActivityResultStatus.INDETERMINATE: "activity_termination_uncertain",
        HarnessGraphActivityResultStatus.FAILED: "activity_failed",
    }.get(status, "activity_failed")
    terminal_payload = {
        "run_id": activity.run_id,
        "graph_id": activity.graph_ref.graph_id,
        "node_id": activity.node_id,
        "activity_id": activity.activity_id,
        "attempt_id": f"graph:{activity.activity_id}:{result.attempt}",
        "attempt_state": status.value,
        "reason_code": reason_code,
        "termination_confirmed": bool(result.termination_confirmed),
        "indeterminate": bool(
            status is HarnessGraphActivityResultStatus.INDETERMINATE
            or not result.termination_confirmed
        ),
        "graph_result_status": status.value,
    }
    evidence = HarnessWorkerEvidence(
        evidence_type="graph_activity_terminal",
        payload=terminal_payload,
    )
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.FAILED,
        diagnostics={"graph_activity_terminal": terminal_payload},
        evidence=(evidence,),
        error=reason_code,
    )


__all__ = ["HarnessGraphPhysicalActivityDispatcher"]
