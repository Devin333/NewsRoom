from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, overload
from uuid import uuid4

from framework.events.canonical import (
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
    EventStreamVersionConflictError,
)
from framework.events.budget import DurableBudgetFactResolver
from framework.harness.control_plane.cumulative_budget import (
    HarnessCumulativeBudgetFact,
    resolve_harness_cumulative_budget_fact,
)
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_CONTRACT,
    HarnessActivity,
    harness_activity_input_checksum,
    validate_activity_call_marker,
)
from framework.harness.control_plane.compensation_runtime import (
    compensation_entry_for_node,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateBinding,
    GateReference,
)
from framework.harness.control_plane.gates import (
    CumulativeLLMBudgetGate,
    DeterministicGate,
    GateContext,
    HarnessGateResult,
    default_plan_gates,
    default_verify_gates,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphActivityCancellationRequest,
    HarnessGraphConcurrentActivityDispatcherPort,
    HarnessGraphActivityDispatcherPort,
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.control_plane.graph_checkpoint import (
    HarnessGraphCheckpoint,
    HarnessGraphDecisionInputSnapshot,
    HarnessGraphHistoryReducer,
    HarnessPinnedDecisionKernel,
    HarnessGraphReplayReport,
    HarnessGraphReplayReadResult,
    graph_history_evidence_ref,
    quarantine_graph_replay_failure,
)
from framework.harness.control_plane.graph_inspection import HarnessGraphInspection
from framework.harness.control_plane.graph_operations import (
    HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID,
    HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION,
    HARNESS_GRAPH_RUN_OPERATION_NODE_ID,
    HarnessGraphRunOperation,
)
from framework.harness.control_plane.graph_evaluator import (
    HarnessAcceptedGraphObservation,
    HarnessGraphEvaluationContext,
    HarnessGraphObservationType,
    merge_branch_output_references,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
    HarnessGraphActivityResultStatus,
    HarnessGraphCommitKind,
    HarnessGraphDecisionCommit,
    HarnessGraphRecovery,
    HarnessGraphTransitionPort,
    InMemoryHarnessGraphTransitionPort,
)
from framework.harness.control_plane.graph_state import (
    HarnessAttemptEvidenceReference,
    HarnessBranchOutputReference,
    HarnessEvidenceKind,
    HarnessGraphState,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    HarnessPendingSideEffectScope,
    HarnessPendingSideEffectState,
    HarnessPendingSideEffectStatus,
    RunLifecycle,
    RunOutcome,
    project_public_legacy_status,
)
from framework.harness.control_plane.phase import (
    HarnessPhase,
    HarnessPhaseBoundary,
    HarnessPhaseRecord,
)
from framework.harness.control_plane.policy import HarnessBudgetSnapshot
from framework.harness.control_plane.scheduler import (
    HarnessGraphStepSchedulingInput,
    HarnessScheduler,
)
from framework.harness.control_plane.step_lifecycle import (
    StepGateObservation,
    StepLifecycleBudget,
    StepLifecycleObservations,
    StepQualityObservation,
    StepWorkerObservation,
)
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepState,
    HarnessStepStatus,
)
from framework.harness.control_plane.transitions import get_step_state
from framework.harness.control_plane.transition import (
    HarnessStateProjection,
    HarnessTransitionCommitted,
    HarnessTransitionKind,
    run_spec_checksum,
)
from framework.harness.quality.verdict import (
    HarnessQualityVerdict,
    aggregate_gate_verdict,
    gate_result_evidence,
)
from framework.harness.side_effects import (
    HarnessFencedSideEffectHandler,
    HarnessFencedSideEffectStorePort,
    HarnessSideEffectApprovalRequest,
    HarnessSideEffectApprovalResolver,
    HarnessSideEffectAttemptLease,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
    HarnessSideEffectRegistry,
    HarnessSideEffectStorePort,
)
from framework.harness.graph.bindings import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.model import (
    HarnessControlNode,
    HarnessContractKind,
    HarnessContractReference,
    HarnessExecutableNode,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    HarnessMergeKind,
    NormalizedHarnessGraph,
)
from framework.harness.graph.runtime_resolution import (
    HarnessGraphRuntimeResolver,
    HarnessResolvedRuntimeBindings,
)
from framework.shared.time import format_datetime
from framework.harness.graph.activity import HarnessStepSpec, HarnessWorkerType
from framework.harness.workflow.spec import HarnessRouteKind
from framework.harness.graph.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.harness.waits.models import (
    HarnessWaitApprovalEvidenceRecord,
    HarnessWaitCancellationRecord,
    HarnessWaitCauseKind,
    HarnessWaitScope,
    HarnessWaitSignal,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
)
from framework.harness.waits.ports import HarnessTimerWakePort

WorkerCallable = Callable[[dict[str, Any]], HarnessWorkerResult]

if TYPE_CHECKING:
    from framework.harness.ports import (
        HarnessGraphResultCommitterPort,
        HarnessGraphResultObserverPort,
        HarnessTransitionPort,
    )


@dataclass(frozen=True)
class HarnessRunResult:
    state: HarnessState
    decisions: tuple[HarnessGraphDecision, ...]
    events: tuple[HarnessEvent, ...]
    worker_results: dict[str, HarnessWorkerResult]
    quality_verdicts: dict[str, HarnessQualityVerdict]
    side_effect_outcomes: dict[str, HarnessSideEffectOutcome] = field(
        default_factory=dict
    )
    graph_state: HarnessGraphState | None = None
    graph_terminal_node_ids: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.state.status == HarnessRunStatus.SUCCEEDED


@dataclass(frozen=True)
class _PreparedSideEffect:
    slot: str
    intent: HarnessSideEffectIntent
    authorization: HarnessSideEffectDecision
    binding: HarnessSideEffectHandlerBinding
    prepare: bool


@dataclass(slots=True)
class _WorkerImplementationAdapter:
    worker_id: str
    worker_version: str
    worker_type: HarnessWorkerType
    delegate: object
    _queued_results: list[HarnessWorkerResult] | None = field(default=None, init=False)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return _invoke_worker_delegate(self, task)


@dataclass(frozen=True, slots=True)
class _ReplayOnlyWorkerDelegate:
    reference: str

    def __call__(self, _task: dict[str, Any]) -> HarnessWorkerResult:
        raise EventIncompleteHistoryError(
            "Graph recovery requires recorded activity evidence; live Worker "
            f"fallback is forbidden for {self.reference}"
        )


@dataclass(frozen=True, slots=True)
class _ActivityImplementationAdapter:
    activity_contract_id: str
    activity_contract_version: str
    event_port: Any
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True,
    )

    def dispatch(self, request: dict[str, Any]) -> HarnessActivity:
        return self.event_port.create_activity(**request)


@dataclass(slots=True)
class _GraphDispatchQueue:
    downstream: HarnessGraphActivityDispatcherPort | None = None
    activities: dict[str, HarnessGraphActivity] = field(default_factory=dict)
    cancellation_requests: dict[
        str,
        HarnessGraphActivityCancellationRequest,
    ] = field(default_factory=dict)
    parallel_capabilities_by_run: dict[
        str,
        dict[str, HarnessActivityCapabilities],
    ] = field(default_factory=dict)
    parallel_dispatchers_by_run: dict[str, object] = field(default_factory=dict)

    def dispatch(self, activity: HarnessGraphActivity) -> None:
        existing = self.activities.get(activity.activity_id)
        if existing is not None and existing != activity:
            raise EventStoreCorruptionError(
                "graph activity identity resolves conflicting descriptors"
            )
        self._validate_pinned_parallel_capabilities(activity)
        self.activities[activity.activity_id] = activity
        if self.downstream is not None:
            self.downstream.dispatch(activity)

    def resolve_parallel_capabilities(
        self,
        activity_refs: tuple[HarnessContractReference, ...],
    ) -> dict[str, HarnessActivityCapabilities]:
        capability_provider = getattr(
            self.downstream,
            "concurrency_capabilities_for",
            None,
        )
        cancellation_handler = getattr(
            self.downstream,
            "request_cancellation",
            None,
        )
        if (
            not isinstance(
                self.downstream,
                HarnessGraphConcurrentActivityDispatcherPort,
            )
            or not callable(capability_provider)
            or not callable(cancellation_handler)
        ):
            return {}
        resolved: dict[str, HarnessActivityCapabilities] = {}
        for activity_ref in activity_refs:
            capabilities = capability_provider(activity_ref)
            if capabilities is None:
                continue
            if not isinstance(capabilities, HarnessActivityCapabilities):
                raise HarnessValidationError(
                    "graph dispatcher returned invalid parallel capability evidence",
                    code="invalid_graph_activity_dispatcher_capabilities",
                    details={"activity_ref": activity_ref.exact_ref},
                )
            resolved[activity_ref.exact_ref] = capabilities
        return resolved

    def pin_parallel_capabilities(
        self,
        run_id: str,
        capabilities: Mapping[str, HarnessActivityCapabilities],
    ) -> None:
        pinned = dict(capabilities)
        existing = self.parallel_capabilities_by_run.get(run_id)
        if existing is not None and existing != pinned:
            raise EventStoreCorruptionError(
                "graph run resolves conflicting dispatcher capability evidence"
            )
        existing_dispatcher = self.parallel_dispatchers_by_run.get(run_id)
        if (
            existing_dispatcher is not None
            and existing_dispatcher is not self.downstream
        ):
            raise EventStoreCorruptionError(
                "graph run resolves parallel capability evidence from multiple dispatchers"
            )
        self.parallel_capabilities_by_run[run_id] = pinned
        self.parallel_dispatchers_by_run[run_id] = self.downstream

    def discard_parallel_capabilities(self, run_id: str) -> None:
        self.parallel_capabilities_by_run.pop(run_id, None)
        self.parallel_dispatchers_by_run.pop(run_id, None)

    def _validate_pinned_parallel_capabilities(
        self,
        activity: HarnessGraphActivity,
    ) -> None:
        pinned = self.parallel_capabilities_by_run.get(activity.run_id)
        if pinned is None:
            return
        expected = pinned.get(activity.activity_ref.exact_ref)
        if expected is None or not expected.parallel_safe:
            return
        capability_provider = getattr(
            self.downstream,
            "concurrency_capabilities_for",
            None,
        )
        cancellation_handler = getattr(
            self.downstream,
            "request_cancellation",
            None,
        )
        if (
            not isinstance(
                self.downstream,
                HarnessGraphConcurrentActivityDispatcherPort,
            )
            or not callable(capability_provider)
            or not callable(cancellation_handler)
        ):
            raise HarnessValidationError(
                "graph dispatcher lost its pinned parallel safety capabilities",
                code="graph_activity_dispatcher_capabilities_changed",
                details={"activity_ref": activity.activity_ref.exact_ref},
            )
        if self.parallel_dispatchers_by_run.get(activity.run_id) is not self.downstream:
            raise HarnessValidationError(
                "graph dispatcher changed after parallel safety preflight",
                code="graph_activity_dispatcher_capabilities_changed",
                details={"activity_ref": activity.activity_ref.exact_ref},
            )
        actual = capability_provider(activity.activity_ref)
        if (
            not isinstance(actual, HarnessActivityCapabilities)
            or not actual.parallel_safe
            or actual != expected
        ):
            raise HarnessValidationError(
                "graph dispatcher parallel safety capabilities changed after preflight",
                code="graph_activity_dispatcher_capabilities_changed",
                details={"activity_ref": activity.activity_ref.exact_ref},
            )

    def request_cancellation(
        self,
        request: HarnessGraphActivityCancellationRequest,
    ) -> None:
        existing = self.cancellation_requests.get(request.request_checksum)
        if existing is not None:
            if existing != request:
                raise EventStoreCorruptionError(
                    "graph cancellation identity resolves conflicting requests"
                )
            return
        handler = (
            None
            if self.downstream is None
            else getattr(self.downstream, "request_cancellation", None)
        )
        if not callable(handler):
            raise HarnessValidationError(
                "active branch cancellation requires a cancellation-capable dispatcher",
                code="graph_activity_cancellation_dispatcher_missing",
                details={"activity_id": request.activity_id},
            )
        handler(request)
        self.cancellation_requests[request.request_checksum] = request


class InMemoryHarnessEventPort:
    """Explicit test-only sink; production composition must use a durable port."""

    def __init__(self) -> None:
        self.events: list[HarnessEvent] = []
        self.activity_results: dict[str, HarnessWorkerResult] = {}
        self.created_activities: list[HarnessActivity] = []
        self._graph_transition_port = InMemoryHarnessGraphTransitionPort()

    def record(self, event: HarnessEvent) -> HarnessEvent:
        self.events.append(event)
        return event

    def create_activity(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt: int,
        activity_type: str,
        inputs: dict[str, Any],
        contract_version: str = HARNESS_ACTIVITY_CONTRACT,
        worker_version: str = "1",
    ) -> HarnessActivity:
        activity = HarnessActivity.for_worker_call(
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            activity_type=activity_type,
            inputs=inputs,
            contract_version=contract_version,
            worker_version=worker_version,
        )
        self.created_activities.append(activity)
        return activity


    def read_history(self, run_id: str) -> tuple[HarnessEvent, ...]:
        return tuple(event for event in self.events if event.run_id == run_id)

    def require_activity_storage(self) -> None:
        return None

    def accept_activity(
        self,
        activity: HarnessActivity,
        inputs: dict[str, Any],
        *,
        accepted_at,
        started_at,
    ) -> HarnessWorkerResult | None:
        del inputs, accepted_at, started_at
        return self.activity_results.get(activity.activity_id)

    def resolve_graph_replay_activity(
        self,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        inputs: dict[str, Any] | None = None,
    ) -> HarnessWorkerResult:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        definition = _graph_definition_by_id(graph, activity.node_id)
        if not isinstance(definition, HarnessExecutableNode):
            raise EventStoreCorruptionError(
                "graph replay activity has no executable definition"
            )
        if inputs is not None and (
            harness_activity_input_checksum(inputs) != activity.input_ref
        ):
            raise EventReplayMismatchError(
                sequence=activity.causal_decision_sequence,
                reason="graph replay activity input conflicts with its descriptor",
            )
        result = self.activity_results.get(activity.activity_id)
        if result is None:
            raise EventIncompleteHistoryError(
                "graph activity result evidence is missing"
            )
        return result

    def record_activity_result(
        self,
        activity: HarnessActivity,
        result: HarnessWorkerResult,
        *,
        completed_at,
    ) -> HarnessEvent:
        existing = self.activity_results.get(activity.activity_id)
        if existing is not None and existing.to_dict() != result.to_dict():
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness activity retry produced a different result",
            )
        self.activity_results[activity.activity_id] = result
        projected = HarnessEvent(
            event_id=activity.result_event_id,
            event_type=HarnessEventType.WORKER_RESULT_RECORDED,
            run_id=activity.run_id,
            step_id=activity.step_id,
            payload={
                "projection_schema": "harness-safe-summary/v1",
                "status": result.status.value,
                "output_ref": checksum_for(result.to_dict()),
                "activity_id": activity.activity_id,
            },
            occurred_at=completed_at,
        )
        if not any(event.event_id == projected.event_id for event in self.events):
            self.events.append(projected)
        return projected

    def initialize_graph(self, *args, **kwargs):
        return self._graph_transition_port.initialize_graph(*args, **kwargs)

    def commit_graph_decision(self, *args, **kwargs):
        return self._graph_transition_port.commit_graph_decision(*args, **kwargs)

    def commit_graph_projection(self, *args, **kwargs):
        return self._graph_transition_port.commit_graph_projection(*args, **kwargs)

    def commit_graph_activity_result(self, *args, **kwargs):
        return self._graph_transition_port.commit_graph_activity_result(*args, **kwargs)

    def commit_graph_observation(self, *args, **kwargs):
        return self._graph_transition_port.commit_graph_observation(*args, **kwargs)

    def recover_graph(self, run_id: str):
        return self._graph_transition_port.recover_graph(run_id)

    def activity_for(self, activity_id: str):
        return self._graph_transition_port.activity_for(activity_id)

    def mark_activity_dispatched(self, activity_id: str) -> None:
        self._graph_transition_port.mark_activity_dispatched(activity_id)


class HarnessControlPlane:
    def __init__(
        self,
        *,
        scheduler: HarnessScheduler | None = None,
        event_port: HarnessTransitionPort | None = None,
        worker_registry: dict[str, WorkerCallable | Iterable[HarnessWorkerResult]]
        | None = None,
        plan_gates: tuple[DeterministicGate, ...] | None = None,
        verify_gates: tuple[DeterministicGate, ...] | None = None,
        gate_registry: DeterministicGateRegistry | None = None,
        side_effect_registry: HarnessSideEffectRegistry | None = None,
        side_effect_store: HarnessSideEffectStorePort | None = None,
        approval_evidence_resolver: HarnessSideEffectApprovalResolver | None = None,
        runtime_binding_authority: HarnessRuntimeBindingAuthority | None = None,
        graph_preflight: HarnessGraphPreflight | None = None,
        legacy_workflow_compiler: object | None = None,
        graph_activity_dispatcher: HarnessGraphActivityDispatcherPort | None = None,
        graph_result_committer: HarnessGraphResultCommitterPort | None = None,
        graph_result_observer: HarnessGraphResultObserverPort | None = None,
        timer_wake_port: HarnessTimerWakePort | None = None,
        side_effect_attempt_owner_id: str | None = None,
        budget_fact_resolver: DurableBudgetFactResolver | None = None,
    ) -> None:
        if event_port is None:
            raise HarnessValidationError(
                "Harness event_port is required; inject InMemoryHarnessEventPort explicitly only in tests"
            )
        if not _is_transition_port(event_port):
            raise HarnessValidationError(
                "Harness event_port must implement durable transition and recovery operations"
            )
        self.scheduler = scheduler or HarnessScheduler()
        self.event_port = event_port
        self.worker_registry = dict(worker_registry or {})
        self.plan_gates = plan_gates or default_plan_gates()
        self.verify_gates = verify_gates or default_verify_gates()
        self.gate_registry = (
            gate_registry if gate_registry is not None else DeterministicGateRegistry()
        )
        if side_effect_registry is not None and not isinstance(
            side_effect_registry,
            HarnessSideEffectRegistry,
        ):
            raise HarnessValidationError(
                "side_effect_registry must be HarnessSideEffectRegistry"
            )
        self.side_effect_registry = side_effect_registry or HarnessSideEffectRegistry()
        self.side_effect_store = side_effect_store
        if side_effect_attempt_owner_id is None:
            side_effect_attempt_owner_id = f"harness-control-plane:{uuid4().hex}"
        elif (
            not isinstance(side_effect_attempt_owner_id, str)
            or not side_effect_attempt_owner_id.strip()
            or side_effect_attempt_owner_id != side_effect_attempt_owner_id.strip()
        ):
            raise HarnessValidationError(
                "side-effect attempt owner id must be a non-blank canonical value",
                code="invalid_side_effect_attempt_owner",
            )
        self._side_effect_attempt_owner_id = side_effect_attempt_owner_id
        self.approval_evidence_resolver = approval_evidence_resolver
        if runtime_binding_authority is not None and not isinstance(
            runtime_binding_authority,
            HarnessRuntimeBindingAuthority,
        ):
            raise TypeError(
                "runtime_binding_authority must be HarnessRuntimeBindingAuthority"
            )
        if graph_preflight is not None and not isinstance(
            graph_preflight,
            HarnessGraphPreflight,
        ):
            raise TypeError("graph_preflight must be HarnessGraphPreflight")
        if legacy_workflow_compiler is not None and not callable(
            getattr(legacy_workflow_compiler, "compile", None)
        ):
            raise TypeError("legacy_workflow_compiler must implement compile")
        self.runtime_binding_authority = runtime_binding_authority
        self.legacy_workflow_compiler = legacy_workflow_compiler
        if timer_wake_port is not None and not isinstance(
            timer_wake_port,
            HarnessTimerWakePort,
        ):
            raise TypeError("timer_wake_port must implement HarnessTimerWakePort")
        self.timer_wake_port = timer_wake_port
        resolver_factory = getattr(event_port, "budget_fact_resolver", None)
        self._budget_fact_resolver = (
            budget_fact_resolver
            if budget_fact_resolver is not None
            else resolver_factory() if callable(resolver_factory) else None
        )
        self.graph_preflight = graph_preflight or HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(),
        )
        graph_transition_port = (
            event_port if isinstance(event_port, HarnessGraphTransitionPort) else None
        )
        self.graph_transition_port = graph_transition_port
        if graph_result_committer is not None and not callable(
            getattr(graph_result_committer, "commit_result", None)
        ):
            raise TypeError(
                "graph_result_committer must implement "
                "HarnessGraphResultCommitterPort"
            )
        self._graph_result_committer = graph_result_committer
        if graph_result_observer is not None and not callable(
            getattr(graph_result_observer, "observe_result", None)
        ):
            raise TypeError(
                "graph_result_observer must implement "
                "HarnessGraphResultObserverPort"
            )
        self._graph_result_observer = graph_result_observer
        self._uses_external_graph_dispatcher = graph_activity_dispatcher is not None
        self._graph_dispatch_queue = _GraphDispatchQueue(graph_activity_dispatcher)
        self._graph_runtime = (
            None
            if graph_transition_port is None
            else HarnessGraphControlPlaneRuntime(
                graph_transition_port,
                activity_dispatcher=self._graph_dispatch_queue,
                side_effect_store=side_effect_store,
                timer_wake_port=timer_wake_port,
            )
        )
        self._committed_events: list[HarnessEvent] = []
        self._gate_bindings_by_run: dict[str, dict[str, tuple[GateBinding, ...]]] = {}
        self._side_effect_bindings_by_run: dict[
            str,
            dict[str, HarnessSideEffectHandlerBinding],
        ] = {}
        self._terminal_side_effect_bindings: dict[
            str, HarnessSideEffectHandlerBinding
        ] = {}
        self._side_effect_intents: dict[str, dict[str, HarnessSideEffectIntent]] = {}
        self._side_effect_outcomes: dict[str, dict[str, HarnessSideEffectOutcome]] = {}
        self._prepared_graphs: dict[str, NormalizedHarnessGraph] = {}
        self._resolved_graph_bindings: dict[
            str,
            HarnessResolvedRuntimeBindings,
        ] = {}
        self._worker_bindings_by_run: dict[str, dict[str, HarnessWorkerBinding]] = {}
        self._activity_contract_versions_by_run: dict[str, dict[str, str]] = {}
        self._prepared_run_specs: dict[str, str] = {}
        self._graph_worker_results: dict[
            str,
            dict[str, HarnessWorkerResult],
        ] = {}
        self._graph_outputs: dict[str, dict[str, Any]] = {}
        self._graph_gate_results: dict[
            str,
            dict[str, tuple[HarnessGateResult, ...]],
        ] = {}
        self._graph_quality_verdicts: dict[
            str,
            dict[str, HarnessQualityVerdict],
        ] = {}
        self._graph_budget_facts: dict[
            str,
            dict[str, HarnessCumulativeBudgetFact],
        ] = {}

    def _require_graph_runtime(self) -> HarnessGraphControlPlaneRuntime:
        if self._graph_runtime is None:
            raise HarnessValidationError(
                "graph execution requires a durable graph transition port",
                code="graph_transition_port_missing",
            )
        return self._graph_runtime

    def _next_graph_sequence(self, run_id: str) -> int:
        return (
            self._require_graph_runtime()
            .transition_port.recover_graph(run_id)
            .expected_last_sequence
            + 1
        )

    def _discard_prepared_graph_run(self, run_id: str) -> None:
        self._graph_dispatch_queue.discard_parallel_capabilities(run_id)
        for cache in (
            self._gate_bindings_by_run,
            self._side_effect_bindings_by_run,
            self._terminal_side_effect_bindings,
            self._prepared_graphs,
            self._resolved_graph_bindings,
            self._worker_bindings_by_run,
            self._activity_contract_versions_by_run,
            self._prepared_run_specs,
            self._graph_worker_results,
            self._graph_outputs,
            self._graph_gate_results,
            self._graph_quality_verdicts,
            self._graph_budget_facts,
        ):
            cache.pop(run_id, None)

    def _validate_prepared_graph_state(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> None:
        if state.run_id != run_spec.run_id:
            raise HarnessValidationError(
                "graph state belongs to another run",
                code="graph_control_state_run_mismatch",
            )
        if (
            state.metadata.get("run_spec_checksum")
            != self._prepared_run_specs[run_spec.run_id]
        ):
            raise HarnessValidationError(
                "graph state does not match the current run specification",
                code="graph_control_run_spec_mismatch",
            )
        if state.graph_ref.checksum != self._prepared_graphs[run_spec.run_id].checksum:
            raise HarnessValidationError(
                "graph state does not match the pinned normalized graph",
                code="graph_control_graph_mismatch",
            )

    def _prepare_run_spec(
        self,
        run_spec: HarnessRunSpec,
        *,
        recovery_only: bool = False,
    ) -> None:
        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        spec_ref = run_spec_checksum(run_spec)
        prepared_ref = self._prepared_run_specs.get(run_spec.run_id)
        if prepared_ref is not None:
            if prepared_ref != spec_ref:
                raise HarnessValidationError(
                    "run_id cannot be reused with a different Harness run spec",
                    details={"run_id": run_spec.run_id},
                )
            return

        steps_by_id = {step.step_id: step for step in run_spec.workflow.steps}
        for rule in run_spec.workflow.routing_rules:
            if rule.kind != HarnessRouteKind.ON_VERDICT:
                continue
            source_step = steps_by_id[rule.from_step]
            if source_step.quality_gate is None:
                raise HarnessValidationError(
                    "ON_VERDICT routing requires a declared deterministic quality gate",
                    code="missing_quality_gate_for_verdict_route",
                    details={
                        "code": "missing_quality_gate_for_verdict_route",
                        "step_id": source_step.step_id,
                    },
                )

        graph = self._graph_replay_recovery(run_spec, compile_only=True)
        self.graph_preflight.validate_static(graph).raise_if_invalid()
        authority = self.runtime_binding_authority or self._legacy_runtime_authority(
            run_spec.workflow,
            graph,
            recovery_only=recovery_only,
        )
        dispatcher_capabilities: dict[str, HarnessActivityCapabilities] | None = None
        if (
            self._uses_external_graph_dispatcher
            and self.graph_preflight.policy.max_parallelism > 1
        ):
            activity_refs = tuple(
                sorted(
                    {
                        node.activity_ref
                        for node in graph.nodes
                        if isinstance(node, HarnessExecutableNode)
                    },
                    key=lambda item: item.exact_ref,
                )
            )
            dispatcher_capabilities = (
                self._graph_dispatch_queue.resolve_parallel_capabilities(activity_refs)
            )
        resolved = HarnessGraphRuntimeResolver(authority).resolve(
            graph,
            parallel_activity_capabilities=dispatcher_capabilities,
            fenced_side_effect_store=isinstance(
                self.side_effect_store,
                HarnessFencedSideEffectStorePort,
            ),
        )
        validation = self.graph_preflight.validate(
            graph,
            registry=resolved.registry_snapshot,
        )
        validation.raise_if_invalid()

        # Plan gates are also committed and replayed, so moving aliases must be
        # rejected before RUN_CREATED even though they are not workflow-bound.
        for gate in self.plan_gates:
            _gate_reference(gate)

        mandatory_by_reference: dict[str, DeterministicGate] = {}
        for gate in self.verify_gates:
            reference = _gate_reference(gate)
            previous = mandatory_by_reference.get(reference)
            if previous is not None and previous is not gate:
                raise HarnessValidationError(
                    "mandatory verify gates contain conflicting implementations for one exact reference",
                    code="conflicting_mandatory_gate_reference",
                    details={
                        "code": "conflicting_mandatory_gate_reference",
                        "reference": reference,
                    },
                )
            mandatory_by_reference[reference] = gate

        bindings: dict[str, tuple[GateBinding, ...]] = {}
        worker_bindings: dict[str, HarnessWorkerBinding] = {}
        activity_contract_versions: dict[str, str] = {}
        side_effect_bindings: dict[str, HarnessSideEffectHandlerBinding] = {}
        for node in graph.nodes:
            if not isinstance(node, HarnessExecutableNode):
                continue
            step = steps_by_id[node.step_id]
            step_bindings = resolved.gates_by_node[node.node_id]
            for binding in step_bindings:
                mandatory = mandatory_by_reference.get(str(binding.reference))
                if mandatory is not None and mandatory is not binding.gate:
                    raise HarnessValidationError(
                        "declared and mandatory gates conflict for one exact reference",
                        code="conflicting_gate_implementation",
                        details={
                            "code": "conflicting_gate_implementation",
                            "reference": str(binding.reference),
                            "step_id": step.step_id,
                        },
                    )
            _bind_step_value(
                bindings,
                step.step_id,
                step_bindings,
                code="ambiguous_step_gate_binding",
            )
            _bind_step_value(
                worker_bindings,
                step.step_id,
                resolved.workers_by_node[node.node_id],
                code="ambiguous_step_worker_binding",
            )
            activity_contract_version = str(
                step.metadata.get(
                    "activity_contract_version",
                    HARNESS_ACTIVITY_CONTRACT,
                )
            )
            _bind_step_value(
                activity_contract_versions,
                step.step_id,
                activity_contract_version,
                code="ambiguous_step_activity_binding",
            )
            side_effect_binding = resolved.side_effects_by_node.get(node.node_id)
            if side_effect_binding is not None:
                _bind_step_value(
                    side_effect_bindings,
                    step.step_id,
                    side_effect_binding,
                    code="ambiguous_step_side_effect_binding",
                )
        for step in run_spec.workflow.steps:
            bindings.setdefault(step.step_id, ())

        terminal_policy = run_spec.workflow.terminal_side_effect_policy
        terminal_binding = resolved.terminal_side_effect
        if terminal_policy is not None:
            if terminal_binding is None:
                raise HarnessValidationError(
                    "terminal side-effect binding was not resolved during graph preflight",
                    code="terminal_side_effect_binding_missing",
                )
            allowed_attempts = run_spec.budget.max_retries_per_step + 1
            if terminal_policy.retry_limit > allowed_attempts:
                raise HarnessValidationError(
                    "terminal side-effect retry limit exceeds the run retry budget",
                    code="terminal_side_effect_retry_limit_exceeded",
                    details={
                        "code": "terminal_side_effect_retry_limit_exceeded",
                        "retry_limit": terminal_policy.retry_limit,
                        "allowed_attempts": allowed_attempts,
                    },
                )
        if (
            side_effect_bindings or terminal_policy is not None
        ) and self.side_effect_store is None:
            raise HarnessValidationError(
                "declared side effects require an injected durable side-effect store",
                code="side_effect_store_missing",
                details={"code": "side_effect_store_missing"},
            )
        if side_effect_bindings or terminal_policy is not None:
            for field_name in ("identity_scope_ref", "subject_scope_ref"):
                scope_ref = run_spec.metadata.get(field_name)
                if not _is_checksum_ref(scope_ref):
                    raise HarnessValidationError(
                        "declared side effects require authoritative checksum scope refs",
                        code="side_effect_scope_missing",
                        details={
                            "code": "side_effect_scope_missing",
                            "scope": field_name,
                        },
                    )
        approval_required = any(
            step.side_effect_handler is not None
            and step.metadata.get("approval_required") is True
            for step in run_spec.workflow.steps
        ) or bool(terminal_policy is not None and terminal_policy.requires_approval)
        if approval_required and self.approval_evidence_resolver is None:
            raise HarnessValidationError(
                "declared side-effect approval policy requires an evidence resolver",
                code="side_effect_approval_resolver_missing",
                details={"code": "side_effect_approval_resolver_missing"},
            )

        self._gate_bindings_by_run[run_spec.run_id] = bindings
        self._side_effect_bindings_by_run[run_spec.run_id] = side_effect_bindings
        if terminal_binding is not None:
            self._terminal_side_effect_bindings[run_spec.run_id] = terminal_binding
        self._prepared_graphs[run_spec.run_id] = graph
        self._resolved_graph_bindings[run_spec.run_id] = resolved
        self._worker_bindings_by_run[run_spec.run_id] = worker_bindings
        self._activity_contract_versions_by_run[run_spec.run_id] = (
            activity_contract_versions
        )
        if dispatcher_capabilities is not None:
            self._graph_dispatch_queue.pin_parallel_capabilities(
                run_spec.run_id,
                dispatcher_capabilities,
            )
        self._prepared_run_specs[run_spec.run_id] = spec_ref

    def _legacy_runtime_authority(
        self,
        workflow,
        graph: NormalizedHarnessGraph,
        *,
        recovery_only: bool = False,
    ) -> HarnessRuntimeBindingAuthority:
        steps_by_id = {step.step_id: step for step in workflow.steps}
        worker_bindings: dict[HarnessContractReference, HarnessWorkerBinding] = {}
        activity_bindings: dict[
            HarnessContractReference,
            HarnessActivityContractBinding,
        ] = {}
        default_activity_ref = HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            HARNESS_ACTIVITY_CONTRACT.rsplit("/", maxsplit=1)[0],
            HARNESS_ACTIVITY_CONTRACT.rsplit("/", maxsplit=1)[1],
        )
        for node in graph.nodes:
            if not isinstance(node, HarnessExecutableNode):
                continue
            step = steps_by_id[node.step_id]
            delegate = self.worker_registry.get(step.step_id)
            if delegate is None:
                delegate = self.worker_registry.get(step.worker_type.value)
            if delegate is None and recovery_only:
                delegate = _ReplayOnlyWorkerDelegate(node.worker_ref.exact_ref)
            if delegate is not None:
                adapter = _WorkerImplementationAdapter(
                    worker_id=node.worker_ref.contract_id,
                    worker_version=node.worker_ref.version,
                    worker_type=step.worker_type,
                    delegate=delegate,
                )
                binding = HarnessWorkerBinding(
                    node.worker_ref,
                    step.worker_type,
                    adapter,
                )
                existing = worker_bindings.get(node.worker_ref)
                if (
                    existing is not None
                    and existing.implementation.delegate is not delegate
                ):
                    raise HarnessValidationError(
                        "one exact worker reference resolves to multiple implementations",
                        code="ambiguous_runtime_worker_binding",
                        details={"reference": node.worker_ref.exact_ref},
                    )
                worker_bindings[node.worker_ref] = binding
            if node.activity_ref == default_activity_ref:
                activity_bindings.setdefault(
                    node.activity_ref,
                    HarnessActivityContractBinding(
                        node.activity_ref,
                        _ActivityImplementationAdapter(
                            activity_contract_id=node.activity_ref.contract_id,
                            activity_contract_version=node.activity_ref.version,
                            event_port=self.event_port,
                        ),
                    ),
                )
        return HarnessRuntimeBindingAuthority(
            workers=tuple(worker_bindings.values()),
            activities=tuple(activity_bindings.values()),
            gate_registry=self.gate_registry,
            side_effect_registry=self.side_effect_registry,
        )

    def initialize(
        self,
        run_spec: HarnessRunSpec,
    ) -> HarnessGraphState:
        return self.initialize_graph(run_spec)

    def initialize_graph(self, run_spec: HarnessRunSpec) -> HarnessGraphState:
        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        was_prepared = run_spec.run_id in self._prepared_run_specs
        try:
            self._prepare_run_spec(run_spec)
            runtime = self._require_graph_runtime()
            return runtime.initialize(
                run_spec,
                self._prepared_graphs[run_spec.run_id],
                self.graph_preflight.policy,
                run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
            )
        except Exception:
            if not was_prepared:
                try:
                    recovery = (
                        None
                        if self.graph_transition_port is None
                        else self.graph_transition_port.recover_graph(run_spec.run_id)
                    )
                except Exception:
                    recovery = None
                if recovery is None or recovery.state is None:
                    self._discard_prepared_graph_run(run_spec.run_id)
            raise

    def next_graph_decision(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        graph_context: HarnessGraphEvaluationContext | None = None,
        step_inputs: tuple[HarnessGraphStepSchedulingInput, ...] = (),
    ) -> HarnessGraphDecision | None:
        self._prepare_run_spec(run_spec)
        self._validate_prepared_graph_state(run_spec, state)
        decision = self.scheduler.next_decision(
            state,
            graph=self._prepared_graphs[run_spec.run_id],
            graph_context=graph_context,
            step_inputs=step_inputs,
        )
        if decision is not None and not isinstance(decision, HarnessGraphDecision):
            raise HarnessValidationError(
                "HarnessScheduler returned a non-graph decision for graph state",
                code="graph_scheduler_decision_type_mismatch",
            )
        return decision

    def apply_graph_decision(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        decision: HarnessGraphDecision,
        *,
        occurred_at,
        activity_input_ref: str | None = None,
        accepted_evidence_refs: tuple[str, ...] = (),
        side_effect_outcome_ref: str | None = None,
    ) -> HarnessGraphState:
        self._prepare_run_spec(run_spec)
        self._validate_prepared_graph_state(run_spec, state)
        return self._require_graph_runtime().apply_decision(
            state,
            self._prepared_graphs[run_spec.run_id],
            decision,
            run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
            occurred_at=occurred_at,
            activity_input_ref=activity_input_ref,
            accepted_evidence_refs=accepted_evidence_refs,
            side_effect_outcome_ref=side_effect_outcome_ref,
        )

    def accept_graph_activity_result(
        self,
        run_spec: HarnessRunSpec,
        result: HarnessGraphActivityResult,
        *,
        occurred_at,
    ) -> HarnessGraphState:
        self._prepare_run_spec(run_spec)
        runtime = self._require_graph_runtime()
        activity = runtime.transition_port.activity_for(result.activity_id)
        if activity is None or activity.run_id != run_spec.run_id:
            raise HarnessValidationError(
                "graph activity result belongs to another or unknown run",
                code="graph_activity_result_run_mismatch",
            )
        state = runtime.accept_activity_result(
            result,
            graph=self._prepared_graphs[run_spec.run_id],
            run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
            occurred_at=occurred_at,
        )
        if state.run_id != run_spec.run_id:
            raise HarnessValidationError(
                "graph activity result belongs to another run",
                code="graph_activity_result_run_mismatch",
            )
        return state

    def accept_graph_observation(
        self,
        run_spec: HarnessRunSpec,
        observation: HarnessAcceptedGraphObservation,
        *,
        occurred_at,
    ) -> HarnessGraphState:
        if observation.observation_type in {
            HarnessGraphObservationType.WAIT_CAUSE,
            HarnessGraphObservationType.RUN_OPERATION,
        }:
            raise HarnessValidationError(
                "Graph control observations must use their typed authorization boundary",
                code=(
                    "graph_wait_typed_boundary_required"
                    if observation.observation_type
                    is HarnessGraphObservationType.WAIT_CAUSE
                    else "graph_run_operation_typed_boundary_required"
                ),
            )
        self._prepare_run_spec(run_spec)
        graph = self._prepared_graphs[run_spec.run_id]
        definition = next(
            (item for item in graph.nodes if item.node_id == observation.node_id),
            None,
        )
        is_pure_merge_result = (
            isinstance(definition, HarnessControlNode)
            and definition.merge is not None
            and definition.merge.merge_kind is HarnessMergeKind.PURE
            and definition.merge.merge_ref is not None
            and observation.observation_type is HarnessGraphObservationType.MERGE_RESULT
        )
        is_wait_cause = (
            isinstance(definition, HarnessControlNode)
            and definition.node_kind is HarnessGraphNodeKind.WAIT
            and definition.wait is not None
            and observation.observation_type is HarnessGraphObservationType.WAIT_CAUSE
        )
        if (
            not isinstance(definition, HarnessExecutableNode)
            and not is_pure_merge_result
            and not is_wait_cause
        ):
            raise HarnessValidationError(
                "graph observation requires a compatible pinned node",
                code="graph_observation_node_kind_mismatch",
            )
        if is_pure_merge_result:
            assert isinstance(definition, HarnessControlNode)
            assert definition.merge is not None
            assert definition.merge.merge_ref is not None
            if observation.contract_ref != definition.merge.merge_ref:
                raise HarnessValidationError(
                    "graph Merge observation is outside the pinned runtime binding",
                    code="graph_observation_contract_mismatch",
                )
        elif is_wait_cause:
            assert isinstance(definition, HarnessControlNode)
            assert definition.wait is not None
            expected = HarnessContractReference(
                HarnessContractKind.WAIT,
                definition.wait.signal_type,
                definition.wait.signal_version,
            )
            if observation.contract_ref != expected:
                raise HarnessValidationError(
                    "Wait cause is outside the pinned Wait contract",
                    code="graph_observation_contract_mismatch",
                )
        elif observation.observation_type in {
            HarnessGraphObservationType.GATE_RESULT,
            HarnessGraphObservationType.QUALITY_VERDICT,
        }:
            assert isinstance(definition, HarnessExecutableNode)
            step_id = definition.step_id
            allowed_gate_refs = {
                *(_gate_reference(gate) for gate in self.plan_gates),
                *(_gate_reference(gate) for gate in self.verify_gates),
                *(
                    str(binding.reference)
                    for binding in self._gate_bindings_by_run.get(
                        run_spec.run_id,
                        {},
                    ).get(step_id, ())
                ),
            }
            if observation.contract_ref.exact_ref not in allowed_gate_refs:
                raise HarnessValidationError(
                    "graph Gate observation is outside the pinned runtime bindings",
                    code="graph_observation_contract_mismatch",
                )
        elif observation.observation_type in {
            HarnessGraphObservationType.SIDE_EFFECT_OUTCOME,
            HarnessGraphObservationType.SIDE_EFFECT_FAILURE,
        }:
            assert isinstance(definition, HarnessExecutableNode)
            allowed_side_effect_refs = {
                str(binding.reference)
                for binding in (
                    self._side_effect_bindings_by_run.get(
                        run_spec.run_id,
                        {},
                    ).get(definition.step_id),
                    self._terminal_side_effect_bindings.get(run_spec.run_id),
                )
                if binding is not None
            }
            if observation.contract_ref.exact_ref not in allowed_side_effect_refs:
                raise HarnessValidationError(
                    "graph side-effect observation is outside pinned runtime bindings",
                    code="graph_observation_contract_mismatch",
                )
        return self._require_graph_runtime().accept_observation(
            observation,
            run_id=run_spec.run_id,
            graph=graph,
            run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
            occurred_at=occurred_at,
        )

    def accept_graph_run_operation(
        self,
        run_spec: HarnessRunSpec,
        operation: HarnessGraphRunOperation,
        *,
        occurred_at,
    ) -> HarnessGraphRunOperation:
        """Commit one typed run operation before the scheduler can act on it."""

        if not isinstance(operation, HarnessGraphRunOperation):
            raise TypeError("operation must be HarnessGraphRunOperation")
        if operation.run_id != run_spec.run_id:
            raise HarnessValidationError(
                "Graph run operation belongs to another run",
                code="graph_run_operation_run_mismatch",
            )
        if operation.accepted_sequence != 0:
            raise HarnessValidationError(
                "new Graph run operation must not supply a stream sequence",
                code="graph_run_operation_sequence_invalid",
            )
        self._prepare_run_spec(run_spec)
        runtime = self._require_graph_runtime()
        recovery = runtime.transition_port.recover_graph(run_spec.run_id)
        existing = _matching_graph_run_operation(recovery, operation)
        if existing is not None:
            return existing
        state = self.recover_graph(run_spec)
        if state.lifecycle in {RunLifecycle.COMPLETED, RunLifecycle.HALTED}:
            raise HarnessValidationError(
                "terminal Graph run cannot accept a new operation",
                code="graph_run_operation_terminal",
            )
        accepted = replace(
            operation,
            accepted_sequence=recovery.expected_last_sequence + 1,
        )
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.RUN_OPERATION,
            HARNESS_GRAPH_RUN_OPERATION_NODE_ID,
            run_spec.run_id,
            0,
            accepted.accepted_sequence,
            HarnessContractReference(
                HarnessContractKind.RUN_OPERATION,
                HARNESS_GRAPH_RUN_OPERATION_CONTRACT_ID,
                HARNESS_GRAPH_RUN_OPERATION_CONTRACT_VERSION,
            ),
            accepted.operation_ref,
            payload={"record": accepted.to_dict()},
        )
        try:
            runtime.accept_observation(
                observation,
                run_id=run_spec.run_id,
                graph=self._prepared_graphs[run_spec.run_id],
                run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
                occurred_at=occurred_at,
            )
        except (EventReplayMismatchError, EventStreamVersionConflictError):
            refreshed = runtime.transition_port.recover_graph(run_spec.run_id)
            existing = _matching_graph_run_operation(refreshed, operation)
            if existing is not None:
                return existing
            raise
        return accepted

    def inspect_graph_wait_scope(
        self,
        run_spec: HarnessRunSpec,
        node_instance_id: str,
    ) -> HarnessWaitScope:
        """Return the exact durable or deterministically resolved Wait scope."""

        self._prepare_run_spec(run_spec)
        state = self.recover_graph(run_spec)
        node = next(
            (
                item
                for item in state.node_instances
                if item.instance_id == node_instance_id
                and (
                    item.node_kind is HarnessGraphNodeKind.WAIT
                    or (
                        item.node_kind is HarnessGraphNodeKind.EXECUTABLE
                        and item.step_status is HarnessStepStatus.WAITING_APPROVAL
                    )
                )
            ),
            None,
        )
        if node is None:
            raise HarnessValidationError(
                "Wait inspection requires an existing Wait node instance",
                code="graph_wait_cause_node_mismatch",
            )
        registration = next(
            (
                item
                for item in state.wait_registrations
                if item.node_instance_id == node.instance_id
            ),
            None,
        )
        if registration is not None:
            return HarnessWaitScope(
                registration.wait_id,
                run_spec.run_id,
                node.instance_id,
                registration.tenant_scope_ref,
                registration.identity_scope_ref,
                registration.signal_schema_ref,
                registration.correlation_ref,
            )
        recovery = self._require_graph_runtime().transition_port.recover_graph(
            run_spec.run_id
        )
        context = self._graph_evaluation_context(run_spec, state, recovery)
        decision = self.next_graph_decision(
            run_spec,
            state,
            graph_context=context,
        )
        raw_registration = (
            decision.payload.get("registration")
            if decision is not None
            and decision.decision_type is HarnessGraphDecisionType.REGISTER_WAIT
            and decision.node_instance_id == node.instance_id
            else None
        )
        if (
            not isinstance(raw_registration, Mapping)
            or raw_registration.get("resolved") is not True
        ):
            raise HarnessValidationError(
                "Wait scope cannot be resolved from accepted graph data",
                code="wait_registration_source_missing",
            )
        return HarnessWaitScope(
            wait_id=raw_registration["wait_id"],
            run_id=run_spec.run_id,
            node_instance_id=node.instance_id,
            tenant_scope_ref=raw_registration["tenant_scope_ref"],
            identity_scope_ref=raw_registration["identity_scope_ref"],
            signal_schema_ref=raw_registration["signal_schema_ref"],
            correlation_ref=raw_registration["correlation_ref"],
        )

    def accept_graph_wait_cause(
        self,
        run_spec: HarnessRunSpec,
        cause: (
            HarnessWaitSignal
            | HarnessWaitTimerWakeRecord
            | HarnessWaitTimeoutRecord
            | HarnessWaitApprovalEvidenceRecord
            | HarnessWaitCancellationRecord
        ),
        *,
        occurred_at,
    ) -> HarnessGraphState:
        """Commit one authorized Wait cause through the canonical graph stream.

        The cause is represented as a graph observation so the existing
        decision/event CAS boundary remains the sole durable source.  This
        method intentionally accepts an immutable, already-authorized record;
        authorization and payload resolution belong to the application layer.
        """

        self._prepare_run_spec(run_spec)
        if isinstance(cause, HarnessWaitSignal):
            cause_kind = HarnessWaitCauseKind.SIGNAL
            cause_ref = cause.signal_ref
            scope = cause.scope
        elif isinstance(cause, HarnessWaitTimerWakeRecord):
            cause_kind = HarnessWaitCauseKind.TIMER
            cause_ref = cause.wake_ref
            scope = cause.scope
        elif isinstance(cause, HarnessWaitTimeoutRecord):
            cause_kind = HarnessWaitCauseKind.TIMEOUT
            cause_ref = cause.timeout_ref
            scope = cause.scope
        elif isinstance(cause, HarnessWaitApprovalEvidenceRecord):
            cause_kind = HarnessWaitCauseKind.APPROVAL
            cause_ref = cause.approval_ref
            scope = cause.scope
        elif isinstance(cause, HarnessWaitCancellationRecord):
            cause_kind = HarnessWaitCauseKind.CANCELLATION
            cause_ref = cause.cancellation_ref
            scope = cause.scope
        else:
            raise TypeError("cause must be a supported immutable Wait record")
        if scope.run_id != run_spec.run_id:
            raise HarnessValidationError(
                "Wait cause belongs to another run",
                code="graph_wait_cause_run_mismatch",
            )
        state = self.recover_graph(run_spec)
        wait_recovery = self._require_graph_runtime().transition_port.recover_graph(
            run_spec.run_id
        )
        cause_identity = _wait_cause_external_identity(cause)
        for commit in wait_recovery.observation_commits:
            if (
                commit.observation.observation_type
                is not HarnessGraphObservationType.WAIT_CAUSE
            ):
                continue
            existing_cause = _wait_cause_from_observation(commit.observation)
            if _wait_cause_external_identity(existing_cause) != cause_identity:
                continue
            if _wait_cause_idempotency_projection(
                existing_cause
            ) != _wait_cause_idempotency_projection(cause):
                raise HarnessValidationError(
                    "Wait cause identity was reused with conflicting content",
                    code=_wait_cause_identity_conflict_code(cause),
                )
            return state
        node = next(
            (
                item
                for item in state.node_instances
                if item.instance_id == scope.node_instance_id
            ),
            None,
        )
        if node is None or (
            node.identity.node_id != scope.wait_id
            and node.metadata.get("wait_id") != scope.wait_id
        ):
            raise HarnessValidationError(
                "Wait cause requires an existing matching Wait node instance",
                code="graph_wait_cause_node_mismatch",
            )
        existing_signal = next(
            (
                item
                for item in state.signal_inbox
                if isinstance(cause, HarnessWaitSignal)
                and item.signal.signal_id == cause.signal_id
                and item.signal.scope.tenant_scope_ref == cause.scope.tenant_scope_ref
            ),
            None,
        )
        if existing_signal is not None:
            if not isinstance(cause, HarnessWaitSignal) or (
                existing_signal.signal.idempotency_projection()
                != cause.idempotency_projection()
            ):
                raise HarnessValidationError(
                    "Wait signal identity was reused with conflicting content",
                    code="wait_signal_identity_conflict",
                )
            return state
        registrations = tuple(
            item
            for item in state.wait_registrations
            if item.node_instance_id == node.instance_id
        )
        registration = (
            None
            if not registrations
            else max(
                registrations,
                key=lambda item: (item.registered_sequence, item.wait_id),
            )
        )
        if registration is None and isinstance(cause, HarnessWaitSignal):
            expected_early_scope = self.inspect_graph_wait_scope(
                run_spec,
                node.instance_id,
            )
            if cause.scope != expected_early_scope:
                raise HarnessValidationError(
                    "early signal does not match the authoritative Wait scope",
                    code="graph_wait_cause_scope_mismatch",
                )
        if not isinstance(cause, HarnessWaitSignal) and registration is None:
            raise HarnessValidationError(
                "non-signal Wait cause requires a durable registration",
                code="graph_wait_registration_missing",
            )
        if registration is not None:
            expected_scope = {
                "wait_id": registration.wait_id,
                "run_id": run_spec.run_id,
                "node_instance_id": node.instance_id,
                "tenant_scope_ref": registration.tenant_scope_ref,
                "identity_scope_ref": registration.identity_scope_ref,
                "signal_schema_ref": registration.signal_schema_ref,
                "correlation_ref": registration.correlation_ref,
            }
            if scope.to_dict() != expected_scope:
                raise HarnessValidationError(
                    "Wait cause does not match the durable registration scope",
                    code="graph_wait_cause_scope_mismatch",
                )
        event_sequence = self._next_graph_sequence(run_spec.run_id)
        if isinstance(cause, HarnessWaitSignal):
            cause = replace(cause, received_sequence=event_sequence)
        elif isinstance(cause, HarnessWaitTimerWakeRecord):
            cause = replace(cause, recorded_sequence=event_sequence)
        elif isinstance(cause, HarnessWaitTimeoutRecord):
            cause = replace(cause, timed_out_sequence=event_sequence)
        elif isinstance(cause, HarnessWaitApprovalEvidenceRecord):
            cause = replace(cause, recorded_sequence=event_sequence)
        else:
            cause = replace(cause, cancelled_sequence=event_sequence)
        if isinstance(cause, HarnessWaitSignal):
            cause_ref = cause.signal_ref
        elif isinstance(cause, HarnessWaitTimerWakeRecord):
            cause_ref = cause.wake_ref
        elif isinstance(cause, HarnessWaitTimeoutRecord):
            cause_ref = cause.timeout_ref
        elif isinstance(cause, HarnessWaitApprovalEvidenceRecord):
            cause_ref = cause.approval_ref
        else:
            cause_ref = cause.cancellation_ref
        definition = next(
            (
                item
                for item in self._prepared_graphs[run_spec.run_id].nodes
                if item.node_id == node.identity.node_id
            ),
            None,
        )
        is_legacy_approval = (
            isinstance(definition, HarnessExecutableNode)
            and registration is not None
            and registration.kind.value == "approval"
        )
        if (
            not (
                isinstance(definition, HarnessControlNode)
                and definition.wait is not None
            )
            and not is_legacy_approval
        ):
            raise HarnessValidationError(
                "Wait cause definition is not a Wait control node",
                code="graph_wait_contract_missing",
            )
        contract_ref = (
            HarnessContractReference(
                HarnessContractKind.WAIT,
                definition.wait.signal_type,
                definition.wait.signal_version,
            )
            if isinstance(definition, HarnessControlNode)
            and definition.wait is not None
            else HarnessContractReference(HarnessContractKind.WAIT, "approval", "1")
        )
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.WAIT_CAUSE,
            definition.node_id,
            node.instance_id,
            node.attempt,
            event_sequence,
            contract_ref,
            cause_ref,
            payload={
                "cause_kind": cause_kind.value,
                "record": cause.to_dict(),
            },
        )
        try:
            return self._require_graph_runtime().accept_observation(
                observation,
                run_id=run_spec.run_id,
                graph=self._prepared_graphs[run_spec.run_id],
                run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
                occurred_at=occurred_at,
            )
        except (EventReplayMismatchError, EventStreamVersionConflictError):
            recovered_state = self.recover_graph(run_spec)
            recovered = self._require_graph_runtime().transition_port.recover_graph(
                run_spec.run_id
            )
            for commit in recovered.observation_commits:
                if (
                    commit.observation.observation_type
                    is not HarnessGraphObservationType.WAIT_CAUSE
                ):
                    continue
                existing_cause = _wait_cause_from_observation(commit.observation)
                if _wait_cause_external_identity(existing_cause) != cause_identity:
                    continue
                if _wait_cause_idempotency_projection(
                    existing_cause
                ) == _wait_cause_idempotency_projection(cause):
                    return recovered_state
                raise HarnessValidationError(
                    "Wait cause identity was reused with conflicting content",
                    code=_wait_cause_identity_conflict_code(cause),
                )
            raise

    def recover_graph(self, run_spec: HarnessRunSpec) -> HarnessGraphState:
        self._prepare_run_spec(run_spec)
        return self._require_graph_runtime().recover(
            run_spec.run_id,
            self._prepared_graphs[run_spec.run_id],
            run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
        )

    @overload
    def _graph_replay_recovery(
        self,
        run_spec: HarnessRunSpec,
        *,
        compile_only: Literal[True],
    ) -> NormalizedHarnessGraph: ...

    @overload
    def _graph_replay_recovery(
        self,
        run_spec: HarnessRunSpec,
        *,
        compile_only: Literal[False] = False,
    ) -> tuple[HarnessGraphRecovery, NormalizedHarnessGraph]: ...

    def _graph_replay_recovery(
        self,
        run_spec: HarnessRunSpec,
        *,
        compile_only: bool = False,
    ) -> NormalizedHarnessGraph | tuple[HarnessGraphRecovery, NormalizedHarnessGraph]:
        """Compile through one pinned adapter and optionally resolve history."""

        if not isinstance(run_spec, HarnessRunSpec):
            raise TypeError("run_spec must be HarnessRunSpec")
        compiler = self.legacy_workflow_compiler
        if compiler is None:
            compiler = HarnessWorkflowGraphCompiler()
            self.legacy_workflow_compiler = compiler
        compiled_graph = compiler.compile(run_spec.workflow).graph
        if compile_only:
            return compiled_graph
        recovery = self._require_graph_runtime().transition_port.recover_graph(
            run_spec.run_id
        )
        if (
            recovery.graph is None
            or recovery.state is None
            or recovery.run_spec_checksum is None
        ):
            raise EventIncompleteHistoryError(
                "graph replay history has no pinned initialization"
            )
        expected_run_spec_ref = run_spec_checksum(run_spec)
        if recovery.run_spec_checksum != expected_run_spec_ref:
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="graph replay run specification checksum mismatch",
            )
        if compiled_graph != recovery.graph:
            raise EventReplayMismatchError(
                sequence=1,
                reason="pinned compiler output differs from recorded graph",
            )
        return recovery, compiled_graph

    def _graph_replay_decision_kernel(
        self,
        run_spec: HarnessRunSpec,
        recovery: HarnessGraphRecovery,
        graph: NormalizedHarnessGraph,
    ) -> HarnessPinnedDecisionKernel:
        """Detach every scheduler input from durable evidence before replay."""

        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "graph replay history has no state projection"
            )
        missing = object()
        cached_graph = self._prepared_graphs.get(run_spec.run_id, missing)
        cached_spec = self._prepared_run_specs.get(run_spec.run_id, missing)
        cached_results = self._graph_worker_results.get(run_spec.run_id, missing)
        cached_outputs = self._graph_outputs.get(run_spec.run_id, missing)
        try:
            # Replay pins only immutable compiler output.  It deliberately does
            # not resolve current Worker, Gate, activity, timer, or effect bindings.
            self._prepared_graphs[run_spec.run_id] = graph
            self._prepared_run_specs[run_spec.run_id] = run_spec_checksum(run_spec)
            self._graph_worker_results[run_spec.run_id] = {}
            self._graph_outputs[run_spec.run_id] = {}
            results_by_attempt = self._graph_replay_worker_results(
                run_spec,
                recovery,
            )
            projections = tuple(
                sorted(recovery.projection_commits, key=lambda item: item.sequence)
            )
            snapshots: dict[int, HarnessGraphDecisionInputSnapshot] = {}
            projection_index = 0
            preceding_state: HarnessGraphState | None = None
            for commit in sorted(
                recovery.decision_commits,
                key=lambda item: item.sequence,
            ):
                while (
                    projection_index < len(projections)
                    and projections[projection_index].sequence < commit.sequence
                ):
                    preceding_state = projections[projection_index].state
                    projection_index += 1
                if preceding_state is None:
                    raise EventIncompleteHistoryError(
                        "graph decision has no preceding state projection"
                    )
                snapshots[commit.sequence] = HarnessGraphDecisionInputSnapshot(
                    graph_context=self._graph_evaluation_context(
                        run_spec,
                        preceding_state,
                        recovery,
                        through_sequence=preceding_state.last_event_sequence,
                    ),
                    step_inputs=self._graph_step_inputs(
                        run_spec,
                        preceding_state,
                        recovery,
                        through_sequence=preceding_state.last_event_sequence,
                        worker_results_by_attempt=results_by_attempt,
                    ),
                )
        finally:
            _restore_cache_value(
                self._prepared_graphs,
                run_spec.run_id,
                cached_graph,
                missing,
            )
            _restore_cache_value(
                self._prepared_run_specs,
                run_spec.run_id,
                cached_spec,
                missing,
            )
            _restore_cache_value(
                self._graph_worker_results,
                run_spec.run_id,
                cached_results,
                missing,
            )
            _restore_cache_value(
                self._graph_outputs,
                run_spec.run_id,
                cached_outputs,
                missing,
            )

        scheduler = HarnessScheduler()

        def verify_decision(
            state: HarnessGraphState,
            commit,
        ) -> HarnessGraphDecision | None:
            snapshot = snapshots.get(commit.sequence)
            if snapshot is None:
                return None
            decision = scheduler.next_decision(
                state,
                graph=graph,
                graph_context=snapshot.graph_context,
                step_inputs=snapshot.step_inputs,
            )
            if decision is not None and not isinstance(
                decision,
                HarnessGraphDecision,
            ):
                raise EventStoreCorruptionError(
                    "pinned graph Scheduler produced a legacy decision"
                )
            return decision

        return HarnessPinnedDecisionKernel(graph, verify_decision)

    def _graph_replay_worker_results(
        self,
        run_spec: HarnessRunSpec,
        recovery: HarnessGraphRecovery,
    ) -> dict[tuple[str, int], HarnessWorkerResult]:
        """Read recorded secure results; never execute a missing activity."""

        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "graph replay history has no state projection"
            )
        result_commits = {
            item.result.activity_id: item for item in recovery.activity_result_commits
        }
        results: dict[tuple[str, int], HarnessWorkerResult] = {}
        for activity in sorted(
            recovery.activities,
            key=lambda item: (
                item.causal_decision_sequence,
                item.node_instance_id,
                item.attempt,
            ),
        ):
            result_commit = result_commits.get(activity.activity_id)
            if result_commit is None:
                continue
            if (
                result_commit.result.status
                is HarnessGraphActivityResultStatus.CANCELLED
            ):
                continue
            definition = _graph_definition_by_id(
                recovery.graph,
                activity.node_id,
            )
            if not isinstance(definition, HarnessExecutableNode):
                raise EventStoreCorruptionError(
                    "recorded graph activity has no executable definition"
                )
            task = self._graph_activity_task(
                run_spec,
                recovery.state,
                activity,
            )
            recorded = self.event_port.resolve_graph_replay_activity(
                activity,
                recovery.graph,
                task,
            )
            worker_result = _coerce_worker_result(recorded)
            if (
                checksum_for(worker_result.to_dict())
                != result_commit.result.payload_ref
            ):
                raise EventReplayMismatchError(
                    sequence=result_commit.sequence,
                    reason="recorded Worker result differs from graph activity evidence",
                )
            key = (activity.node_instance_id, activity.attempt)
            existing = results.get(key)
            if existing is not None and existing.to_dict() != worker_result.to_dict():
                raise EventStoreCorruptionError(
                    "one graph attempt resolves conflicting Worker results"
                )
            results[key] = worker_result
            self._graph_worker_results[run_spec.run_id][activity.node_instance_id] = (
                worker_result
            )
        return results

    def rebuild_graph_history(
        self,
        run_spec: HarnessRunSpec,
        *,
        checkpoint: HarnessGraphCheckpoint | None = None,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayReport:
        """Rebuild one graph projection without invoking live runtime adapters."""

        recovery, _ = self._graph_replay_recovery(run_spec)
        return HarnessGraphHistoryReducer().rebuild(
            recovery,
            checkpoint=checkpoint,
            through_sequence=through_sequence,
        )

    def verify_graph_history(
        self,
        run_spec: HarnessRunSpec,
        *,
        checkpoint: HarnessGraphCheckpoint | None = None,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayReport:
        """Verify reducers and the exact pinned compiler/scheduler kernel."""

        recovery, compiled_graph = self._graph_replay_recovery(run_spec)
        decision_kernel = self._graph_replay_decision_kernel(
            run_spec,
            recovery,
            compiled_graph,
        )
        return HarnessGraphHistoryReducer().rebuild(
            recovery,
            checkpoint=checkpoint,
            through_sequence=through_sequence,
            decision_kernel=decision_kernel,
            verify_history=True,
        )

    def verify_graph_history_or_quarantine(
        self,
        run_spec: HarnessRunSpec,
        *,
        checkpoint: HarnessGraphCheckpoint | None = None,
        through_sequence: int | None = None,
    ) -> HarnessGraphReplayReadResult:
        """Fail closed with a bounded reason and no source payload diagnostic."""

        try:
            report = self.verify_graph_history(
                run_spec,
                checkpoint=checkpoint,
                through_sequence=through_sequence,
            )
        except (
            EventIncompleteHistoryError,
            EventReplayMismatchError,
            EventStoreCorruptionError,
            HarnessValidationError,
            TypeError,
            ValueError,
        ) as exc:
            return quarantine_graph_replay_failure(exc)
        return HarnessGraphReplayReadResult(report=report)

    def create_graph_checkpoint(
        self,
        run_spec: HarnessRunSpec,
        checkpoint_id: str,
        *,
        created_at,
    ) -> HarnessGraphCheckpoint:
        """Create a checksum-bound checkpoint from a verified durable projection."""

        report = self.verify_graph_history(run_spec)
        recovery, _ = self._graph_replay_recovery(run_spec)
        history_evidence_ref = graph_history_evidence_ref(
            recovery,
            through_sequence=report.state.last_event_sequence,
            projection_checksum=report.projection_checksum,
        )
        return HarnessGraphCheckpoint.from_state(
            checkpoint_id,
            report.state,
            created_at=created_at,
            history_evidence_ref=history_evidence_ref,
        )

    def inspect_graph(
        self,
        run_spec: HarnessRunSpec,
        *,
        verify_history: bool = False,
    ) -> HarnessGraphInspection:
        """Return the bounded safe graph projection for an authorized caller."""

        state = self.recover_graph(run_spec)
        replay_report = self.verify_graph_history(run_spec) if verify_history else None
        return HarnessGraphInspection.from_state(
            state,
            replay_report=replay_report,
        )

    def _drive_graph(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        initial_decisions: Iterable[HarnessGraphDecision] = (),
    ) -> HarnessRunResult:
        """Drive one pinned graph through the single scheduler boundary.

        The method deliberately keeps Worker/Gate adapters here, while all
        readiness, routing, and terminal decisions remain Scheduler outputs.
        ``HarnessState`` is created only as a read-only adapter for existing
        Gate and side-effect contracts; it never supplies Graph routing state.
        """

        run_id = run_spec.run_id
        graph = self._prepared_graphs[run_id]
        decisions: list[HarnessGraphDecision] = list(initial_decisions)
        self._hydrate_graph_execution(run_spec, state)
        self._restore_graph_auxiliary_recovery(run_spec)

        while state.lifecycle not in {
            RunLifecycle.COMPLETED,
            RunLifecycle.HALTED,
        }:
            state = self.recover_graph(run_spec)
            state = self._reconcile_graph_activities(run_spec, state)
            state = self._reconcile_graph_merges(run_spec, state)
            self._hydrate_graph_execution(run_spec, state)
            recovery = self._require_graph_runtime().transition_port.recover_graph(
                run_id
            )
            reconciled_verify_state = self._reconcile_graph_verify_gates(
                run_spec,
                state,
                recovery,
            )
            if (
                reconciled_verify_state.projection_checksum
                != state.projection_checksum
            ):
                state = reconciled_verify_state
                continue
            reconciled_side_effect_state = self._reconcile_graph_side_effects(
                run_spec,
                state,
            )
            if (
                reconciled_side_effect_state.projection_checksum
                != state.projection_checksum
            ):
                state = reconciled_side_effect_state
                continue
            context = self._graph_evaluation_context(run_spec, state, recovery)
            step_inputs = self._graph_step_inputs(run_spec, state, recovery)
            decision = self.next_graph_decision(
                run_spec,
                state,
                graph_context=context,
                step_inputs=step_inputs,
            )
            if decision is None:
                if state.lifecycle is RunLifecycle.WAITING:
                    break
                if self._uses_external_graph_dispatcher and state.active_activities:
                    break
                raise EventIncompleteHistoryError(
                    "graph scheduler reached a non-terminal state without a decision"
                )
            if not isinstance(decision, HarnessGraphDecision):
                raise HarnessValidationError(
                    "graph scheduler returned a legacy decision",
                    code="graph_scheduler_decision_type_mismatch",
                )
            occurred_at = _graph_time(
                run_spec,
                recovery.expected_last_sequence + 1,
            )
            step_id = self._graph_step_id(graph, decision.node_id)
            worker_result = self._graph_worker_for_decision(
                run_id,
                decision.node_instance_id,
            )
            side_effect_outcome_ref = _graph_side_effect_outcome_for_completion(
                state,
                decision,
            )
            state = self.apply_graph_decision(
                run_spec,
                state,
                decision,
                occurred_at=occurred_at,
                activity_input_ref=(
                    None
                    if decision.decision_type
                    is not HarnessGraphDecisionType.DISPATCH_ACTIVITY
                    else self._graph_activity_input_ref(run_spec, state, decision)
                ),
                accepted_evidence_refs=decision.evidence_refs,
                side_effect_outcome_ref=side_effect_outcome_ref,
            )
            decisions.append(decision)

            if decision.decision_type is HarnessGraphDecisionType.ENTER_STEP_PHASE:
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.PLAN,
                    HarnessPhaseBoundary.ENTRY,
                    state,
                )
                state = self._run_graph_plan_gates(
                    run_spec,
                    state,
                    step_id,
                    worker_result=None,
                )
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.PLAN,
                    HarnessPhaseBoundary.EXIT,
                    state,
                )
            elif decision.decision_type is HarnessGraphDecisionType.DISPATCH_ACTIVITY:
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.EXECUTE,
                    HarnessPhaseBoundary.ENTRY,
                    state,
                )
                self._process_graph_dispatches(run_spec)
                state = self.recover_graph(run_spec)
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.EXECUTE,
                    HarnessPhaseBoundary.EXIT,
                    state,
                )
            elif (
                decision.decision_type
                is HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT
            ):
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.VERIFY,
                    HarnessPhaseBoundary.ENTRY,
                    state,
                )
                state = self._run_graph_verify_gates(
                    run_spec,
                    state,
                    step_id,
                    worker_result,
                )
                self._record_graph_phase(
                    run_spec,
                    step_id,
                    HarnessPhase.VERIFY,
                    HarnessPhaseBoundary.EXIT,
                    state,
                )
            elif decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE:
                state = self.recover_graph(run_spec)
                state = self._record_graph_verified_output(
                    run_spec,
                    state,
                    decision.node_instance_id,
                    worker_result,
                )
            self._graph_dispatch_queue.activities.clear()
            state = self.recover_graph(run_spec)

        return self._graph_result(
            run_spec,
            state,
            decisions=decisions,
        )

    def _graph_result(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        decisions: list[HarnessGraphDecision],
    ) -> HarnessRunResult:
        worker_results_by_step: dict[str, HarnessWorkerResult] = {}
        quality_by_step: dict[str, HarnessQualityVerdict] = {}
        worker_by_instance = self._graph_worker_results.get(run_spec.run_id, {})
        quality_by_instance = self._graph_quality_verdicts.get(run_spec.run_id, {})
        for node in state.node_instances:
            if node.step_id is None:
                continue
            if node.instance_id in worker_by_instance:
                worker_results_by_step[node.step_id] = worker_by_instance[
                    node.instance_id
                ]
            if node.instance_id in quality_by_instance:
                quality_by_step[node.step_id] = quality_by_instance[node.instance_id]
        compatibility = self._graph_compat_state(
            run_spec,
            state,
            step_id=None,
            outputs=self._graph_outputs.get(run_spec.run_id, {}),
            worker_result=None,
        )
        return HarnessRunResult(
            state=compatibility,
            decisions=tuple(decisions),
            events=tuple(
                event
                for event in self._committed_events
                if event.run_id == run_spec.run_id
            ),
            worker_results=worker_results_by_step,
            quality_verdicts=quality_by_step,
            side_effect_outcomes=dict(
                self._side_effect_outcomes.get(run_spec.run_id, {})
            ),
            graph_state=state,
            graph_terminal_node_ids=(
                ()
                if self._prepared_graphs.get(run_spec.run_id) is None
                else self._prepared_graphs[run_spec.run_id].terminal_node_ids
            ),
        )

    def _hydrate_graph_execution(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> None:
        run_id = run_spec.run_id
        for event in self.event_port.read_history(run_id):
            if not any(
                item.event_id == event.event_id for item in self._committed_events
            ):
                self._committed_events.append(event)
        worker_results: dict[str, HarnessWorkerResult] = {}
        self._graph_worker_results[run_id] = worker_results
        self._graph_budget_facts[run_id] = {}
        self._graph_outputs[run_id] = {}
        recovery = self._require_graph_runtime().transition_port.recover_graph(run_id)
        graph = self._prepared_graphs[run_id]
        result_by_activity = {
            item.result.activity_id: item for item in recovery.activity_result_commits
        }
        for activity in sorted(
            recovery.activities,
            key=lambda item: (
                item.causal_decision_sequence,
                item.node_instance_id,
                item.attempt,
            ),
        ):
            result_commit = result_by_activity.get(activity.activity_id)
            if result_commit is None:
                continue
            if (
                result_commit.result.status
                is HarnessGraphActivityResultStatus.CANCELLED
            ):
                continue
            recorded = self.event_port.resolve_graph_replay_activity(
                activity,
                graph,
            )
            result = _coerce_worker_result(recorded)
            worker_results[activity.node_instance_id] = result
            fact = resolve_harness_cumulative_budget_fact(
                run_id=run_id,
                worker_result=result,
                resolver=self._budget_fact_resolver,
            )
            if fact is not None:
                self._graph_budget_facts[run_id][activity.node_instance_id] = fact
                self._record_or_validate_budget_fact(
                    run_spec,
                    activity,
                    fact,
                )
        definitions = {item.node_id: item for item in graph.nodes}
        for node in state.node_instances:
            if (
                node.node_kind is not HarnessGraphNodeKind.MERGE
                or node.status is not HarnessNodeInstanceStatus.SUCCEEDED
            ):
                continue
            definition = definitions.get(node.identity.node_id)
            if (
                not isinstance(definition, HarnessControlNode)
                or definition.merge is None
            ):
                raise EventIncompleteHistoryError(
                    "successful Merge node has no pinned contract"
                )
            if definition.merge.merge_kind is HarnessMergeKind.PURE:
                merge_outputs = node.metadata.get("merge_outputs")
                if not isinstance(merge_outputs, Mapping):
                    raise EventIncompleteHistoryError(
                        "successful pure Merge is missing its durable output manifest"
                    )
                continue
            aggregation_id = node.metadata.get("aggregation_node_instance_id")
            aggregation_result = (
                None
                if not isinstance(aggregation_id, str)
                else worker_results.get(aggregation_id)
            )
            aggregation_node = (
                None
                if not isinstance(aggregation_id, str)
                else next(
                    (
                        item
                        for item in state.node_instances
                        if item.instance_id == aggregation_id
                    ),
                    None,
                )
            )
            if aggregation_result is None or aggregation_node is None:
                raise EventIncompleteHistoryError(
                    "successful aggregation Merge is missing its recorded Worker result"
                )
            aggregation_definition = definitions.get(aggregation_node.identity.node_id)
            if (
                not isinstance(aggregation_definition, HarnessExecutableNode)
                or len(aggregation_definition.output_keys) != 1
            ):
                raise EventIncompleteHistoryError(
                    "aggregation Merge output contract is invalid"
                )
        self._graph_outputs[run_id] = self._graph_root_output_projection(
            run_spec,
            state,
        )
        gate_cache = self._graph_gate_results.setdefault(run_id, {})
        quality_cache = self._graph_quality_verdicts.setdefault(run_id, {})
        for node in state.node_instances:
            verify_commits = tuple(
                item
                for item in recovery.decision_commits
                if item.decision.node_instance_id == node.instance_id
                and item.decision.decision_type
                is HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT
            )
            if not verify_commits:
                continue
            boundary = verify_commits[-1].sequence
            latest_gates: dict[str, HarnessAcceptedGraphObservation] = {}
            latest_quality: HarnessAcceptedGraphObservation | None = None
            for commit in recovery.observation_commits:
                observation = commit.observation
                if (
                    observation.node_instance_id != node.instance_id
                    or observation.attempt != node.attempt
                    or observation.event_sequence <= boundary
                ):
                    continue
                if (
                    observation.observation_type
                    is HarnessGraphObservationType.GATE_RESULT
                ):
                    latest_gates[observation.contract_ref.exact_ref] = observation
                elif (
                    observation.observation_type
                    is HarnessGraphObservationType.QUALITY_VERDICT
                ):
                    latest_quality = observation
            if latest_gates:
                gate_cache.setdefault(
                    node.instance_id,
                    tuple(
                        HarnessGateResult(
                            gate_name=item.contract_ref.contract_id,
                            passed=bool(item.payload["passed"]),
                            details={
                                "harness_gate": {
                                    "reference": item.contract_ref.exact_ref,
                                    "input_ref": item.payload["input_ref"],
                                    "result_ref": item.payload["result_ref"],
                                    "reason_code": item.payload["reason_code"],
                                }
                            },
                        )
                        for item in sorted(
                            latest_gates.values(),
                            key=lambda value: (
                                value.event_sequence,
                                value.contract_ref.exact_ref,
                            ),
                        )
                    ),
                )
            if latest_quality is not None:
                quality_cache.setdefault(
                    node.instance_id,
                    HarnessQualityVerdict(
                        passed=bool(latest_quality.payload["passed"]),
                        score=latest_quality.payload["score"],
                    ),
                )

    def _restore_graph_auxiliary_recovery(
        self,
        run_spec: HarnessRunSpec,
    ) -> None:
        history = self.event_port.read_history(run_spec.run_id)
        if not isinstance(history, tuple) or not all(
            isinstance(event, HarnessEvent) for event in history
        ):
            raise HarnessValidationError(
                "Harness transition port returned an invalid history projection"
            )
        self._committed_events = list(history)

        if self.side_effect_store is None:
            return
        outcomes = self._side_effect_outcomes.setdefault(run_spec.run_id, {})
        for authorization in self.side_effect_store.list_decisions(
            run_id=run_spec.run_id
        ):
            outcome = self.side_effect_store.get_outcome(
                effect_id=authorization.effect_id,
                identity_scope_ref=authorization.identity_scope_ref,
                subject_scope_ref=authorization.subject_scope_ref,
                idempotency_key=authorization.idempotency_key,
            )
            if outcome is None:
                continue
            slot = (
                authorization.step_id
                if authorization.origin is HarnessSideEffectOrigin.WORKER
                else "__terminal__"
                if authorization.origin is HarnessSideEffectOrigin.CONTROLLER_TERMINAL
                else None
            )
            if slot is None:
                continue
            existing = outcomes.get(slot)
            if existing is not None and existing != outcome:
                raise EventStoreCorruptionError(
                    "multiple durable side-effect outcomes occupy one Graph slot"
                )
            outcomes[slot] = outcome

    def _reconcile_graph_side_effects(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> HarnessGraphState:
        pending_values: list[HarnessPendingSideEffectState] = []
        for node in state.node_instances:
            raw_pending = node.metadata.get("pending_side_effect")
            if not isinstance(raw_pending, Mapping):
                continue
            pending = HarnessPendingSideEffectState.from_dict(raw_pending)
            if pending.status is HarnessPendingSideEffectStatus.PREPARED:
                pending_values.append(pending)
        raw_terminal = state.metadata.get("pending_terminal_side_effect")
        if isinstance(raw_terminal, Mapping):
            pending = HarnessPendingSideEffectState.from_dict(raw_terminal)
            if pending.status is HarnessPendingSideEffectStatus.PREPARED:
                pending_values.append(pending)
        if not pending_values:
            return state

        pending = min(
            pending_values,
            key=lambda item: (
                item.prepare_sequence,
                item.node_instance_id,
                item.prepare_decision_ref,
            ),
        )
        recovery = self._require_graph_runtime().transition_port.recover_graph(
            run_spec.run_id
        )
        commit = next(
            (
                item
                for item in recovery.decision_commits
                if item.decision.decision_checksum
                == pending.prepare_decision_ref
            ),
            None,
        )
        if not isinstance(commit, HarnessGraphDecisionCommit) or (
            commit.sequence != pending.prepare_sequence
            or commit.decision.decision_type
            is not HarnessGraphDecisionType.PREPARE_SIDE_EFFECT
        ):
            raise EventIncompleteHistoryError(
                "pending Graph side effect lacks its durable prepare decision"
            )
        node = _graph_node_by_instance(state, pending.node_instance_id)
        worker_result = self._graph_worker_results.get(run_spec.run_id, {}).get(
            node.instance_id
        )
        decision_input = self._graph_side_effect_input(
            commit.decision,
            command_ordinal=commit.sequence,
        )
        if pending.scope is HarnessPendingSideEffectScope.NODE_INSTANCE:
            if node.step_id is None:
                raise EventIncompleteHistoryError(
                    "pending node side effect lacks its Step identity"
                )
            compat_state = self._graph_compat_state(
                run_spec,
                state,
                step_id=node.step_id,
                outputs=self._graph_scoped_output_projection(
                    run_spec,
                    state,
                    node_instance_id=node.instance_id,
                ),
                worker_result=worker_result,
            )
            prepared = self._prepare_worker_side_effect(
                compat_state,
                decided_at=commit.occurred_at,
                decision_input=decision_input,
                step_id=node.step_id,
                worker_result=worker_result,
                gate_results=self._graph_gate_results_for_step(
                    run_spec.run_id,
                    node.instance_id,
                ),
                quality_verdict=self._graph_quality_verdict_for_step(
                    run_spec.run_id,
                    node.instance_id,
                ),
            )
        else:
            compat_state = self._graph_compat_state(
                run_spec,
                state,
                step_id=node.step_id,
                outputs=self._graph_outputs.get(run_spec.run_id, {}),
                worker_result=worker_result,
            )
            prepared = self._prepare_terminal_side_effect(
                compat_state,
                decided_at=commit.occurred_at,
                decision_input=decision_input,
            )
        if prepared is None or (
            str(prepared.binding.reference) != pending.handler_ref.exact_ref
            or prepared.authorization.causation_id
            != pending.prepare_decision_ref
            or prepared.authorization.command_ordinal != pending.prepare_sequence
        ):
            raise EventIncompleteHistoryError(
                "pending Graph side effect cannot resolve its exact runtime authorization"
            )
        try:
            outcome = self._execute_prepared_side_effect(prepared)
        except HarnessValidationError as exc:
            if exc.code not in {
                "effect_retry_exhausted",
                "side_effect_attempt_indeterminate",
            }:
                raise
            return self._record_graph_side_effect_failure(
                run_spec,
                state,
                commit.decision,
                prepared,
                compat_state=compat_state,
                reason_code=exc.code,
            )
        return self._record_graph_side_effect_outcome(
            run_spec,
            state,
            pending,
            prepared,
            outcome,
        )

    def _record_graph_side_effect_outcome(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        pending: HarnessPendingSideEffectState,
        prepared: _PreparedSideEffect,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessGraphState:
        if not isinstance(outcome.checksum, str) or not _is_checksum_ref(
            outcome.checksum
        ):
            raise EventStoreCorruptionError(
                "durable side-effect outcome is missing its checksum"
            )
        if outcome.decision_ref != prepared.authorization.checksum:
            raise EventStoreCorruptionError(
                "durable side-effect outcome conflicts with its authorization"
            )
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.SIDE_EFFECT_OUTCOME,
            pending.node_id,
            pending.node_instance_id,
            pending.attempt,
            self._next_graph_sequence(run_spec.run_id),
            pending.handler_ref,
            outcome.checksum,
            payload={
                "scope": pending.scope.value,
                "prepare_decision_ref": pending.prepare_decision_ref,
                "decision_ref": prepared.authorization.checksum,
                "outcome_ref": outcome.checksum,
                "effect_ref": checksum_for(outcome.effect_id),
                "disposition": outcome.disposition.value,
            },
        )
        return self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )

    def _record_graph_side_effect_failure(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        decision: HarnessGraphDecision,
        prepared: _PreparedSideEffect,
        *,
        compat_state: HarnessState,
        reason_code: str,
    ) -> HarnessGraphState:
        node = None
        if decision.node_instance_id is not None:
            node = _graph_node_by_instance(state, decision.node_instance_id)
        else:
            raw_pending = state.metadata.get("pending_terminal_side_effect")
            if isinstance(raw_pending, Mapping):
                pending = HarnessPendingSideEffectState.from_dict(raw_pending)
                node = _graph_node_by_instance(state, pending.node_instance_id)
        if node is None:
            raise EventIncompleteHistoryError(
                "side-effect failure has no exact prepared observation anchor"
            )
        reference = HarnessContractReference(
            HarnessContractKind.SIDE_EFFECT,
            prepared.binding.reference.handler_id,
            prepared.binding.reference.version,
        )
        if reason_code not in {
            "effect_retry_exhausted",
            "side_effect_attempt_indeterminate",
        }:
            raise HarnessValidationError(
                "unsupported graph side-effect failure reason",
                code="invalid_graph_side_effect_failure",
            )
        failure = {
            "code": reason_code,
            "effect_ref": checksum_for(prepared.intent.effect_id),
            "decision_ref": prepared.authorization.checksum,
        }
        failure_ref = checksum_for(failure)
        payload = {
            "decision_ref": prepared.authorization.checksum,
            "failure_ref": failure_ref,
            "reason_code": reason_code,
            "causal_graph_decision_checksum": decision.decision_checksum,
        }
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.SIDE_EFFECT_FAILURE,
            node.identity.node_id,
            node.instance_id,
            node.attempt,
            self._next_graph_sequence(run_spec.run_id),
            reference,
            failure_ref,
            payload=payload,
        )
        projected = self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )
        indeterminate = reason_code == "side_effect_attempt_indeterminate"
        if not indeterminate:
            self._quarantine_prepared_side_effects(compat_state)
        return projected

    def _process_graph_dispatches(self, run_spec: HarnessRunSpec) -> None:
        if self._uses_external_graph_dispatcher:
            return
        activities = tuple(
            sorted(
                self._graph_dispatch_queue.activities.values(),
                key=lambda item: (
                    item.causal_decision_sequence,
                    item.node_instance_id,
                ),
            )
        )
        for activity in activities:
            self._process_graph_activity(run_spec, activity)

    def _reconcile_graph_activities(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> HarnessGraphState:
        if not state.active_activities:
            return state
        if self._uses_external_graph_dispatcher:
            return state
        port = self._require_graph_runtime().transition_port
        recovery = port.recover_graph(run_spec.run_id)
        completed_ids = {
            item.result.activity_id for item in recovery.activity_result_commits
        }
        for active in state.active_activities:
            if active.activity_id in completed_ids:
                continue
            activity = port.activity_for(active.activity_id)
            if activity is None:
                raise EventIncompleteHistoryError(
                    "active graph attempt is missing its durable activity descriptor"
                )
            self._process_graph_activity(run_spec, activity)
            state = self.recover_graph(run_spec)
        return state

    def _reconcile_graph_merges(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> HarnessGraphState:
        graph = self._prepared_graphs[run_spec.run_id]
        for node in state.node_instances:
            if (
                node.node_kind is not HarnessGraphNodeKind.MERGE
                or node.status is not HarnessNodeInstanceStatus.RUNNING
            ):
                continue
            definition = next(
                (item for item in graph.nodes if item.node_id == node.identity.node_id),
                None,
            )
            if (
                not isinstance(definition, HarnessControlNode)
                or definition.merge is None
                or definition.merge.merge_kind is not HarnessMergeKind.PURE
            ):
                raise EventIncompleteHistoryError(
                    "running Merge node has no pure merge contract"
                )
            state = self._execute_pure_graph_merge(
                run_spec,
                state,
                node,
                definition,
            )
        return state

    def _execute_pure_graph_merge(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        node: HarnessNodeInstanceState,
        definition: HarnessControlNode,
    ) -> HarnessGraphState:
        contract = definition.merge
        if contract is None or contract.merge_ref is None:
            raise EventIncompleteHistoryError(
                "pure Merge execution is missing its exact binding"
            )
        resolved = self._resolved_graph_bindings.get(run_spec.run_id)
        binding = (
            None
            if resolved is None
            else resolved.merges_by_reference.get(contract.merge_ref.exact_ref)
        )
        if binding is None:
            raise HarnessValidationError(
                "exact pure Merge binding is unavailable",
                code="unknown_runtime_contract_binding",
                details={"reference": contract.merge_ref.exact_ref},
            )
        raw_inputs = node.metadata.get("merge_input_refs")
        operation_id = node.metadata.get("merge_operation_id")
        input_checksum = node.metadata.get("merge_input_checksum")
        if (
            not isinstance(raw_inputs, tuple)
            or not isinstance(operation_id, str)
            or not isinstance(input_checksum, str)
        ):
            raise EventIncompleteHistoryError(
                "running Merge node is missing its committed input identity"
            )
        input_refs = tuple(
            HarnessBranchOutputReference.from_dict(item) for item in raw_inputs
        )
        request = {
            "operation_id": operation_id,
            "input_checksum": input_checksum,
            "branch_outputs": tuple(item.to_dict() for item in input_refs),
        }
        succeeded = False
        outputs: Mapping[str, Any] = {}
        reason_code = "merge_execution_failed"
        try:
            candidate = binding.implementation(request)
            normalized = normalize_canonical_json(candidate, path="$.merge_result")
            if not isinstance(normalized, Mapping):
                raise HarnessValidationError(
                    "pure Merge binding must return an object",
                    code="graph_merge_output_contract_mismatch",
                )
            if set(normalized) != set(contract.output_keys):
                raise HarnessValidationError(
                    "pure Merge result keys do not match its output contract",
                    code="graph_merge_output_contract_mismatch",
                )
            allowed_refs = {
                value
                for item in input_refs
                for value in (item.payload_ref, item.producer_terminal_ref)
            }
            for value in normalized.values():
                _validate_merge_reference_manifest(value, allowed_refs=allowed_refs)
            outputs = normalized
            succeeded = True
            reason_code = "merge_succeeded"
        except Exception:  # noqa: BLE001 - deterministic failure becomes evidence
            outputs = {}
        output_refs = {key: checksum_for(value) for key, value in outputs.items()}
        payload = {
            "operation_id": operation_id,
            "input_checksum": input_checksum,
            "input_refs": [item.to_dict() for item in input_refs],
            "succeeded": succeeded,
            "output_refs": output_refs,
            "outputs": thaw_canonical_json(outputs),
            "reason_code": reason_code,
        }
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.MERGE_RESULT,
            definition.node_id,
            node.instance_id,
            0,
            self._next_graph_sequence(run_spec.run_id),
            contract.merge_ref,
            checksum_for(
                {
                    "operation_id": operation_id,
                    "succeeded": succeeded,
                    "output_refs": output_refs,
                    "reason_code": reason_code,
                }
            ),
            payload=payload,
        )
        return self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )

    def _process_graph_activity(
        self,
        run_spec: HarnessRunSpec,
        activity: HarnessGraphActivity,
    ) -> None:
        run_id = run_spec.run_id
        definition = self._graph_definition(run_id, activity.node_id)
        step = self._graph_step(run_spec, definition.step_id)
        current_state = self.recover_graph(run_spec)
        task = self._graph_activity_task(run_spec, current_state, activity)
        if harness_activity_input_checksum(task) != activity.input_ref:
            raise EventReplayMismatchError(
                sequence=activity.causal_decision_sequence,
                reason="graph activity input no longer matches its committed descriptor",
            )
        compensation_task = task.get("compensation")
        is_compensation = isinstance(compensation_task, Mapping)
        event_activity = _event_activity_from_graph(activity, step)
        accepted_at = _graph_time(run_spec, activity.causal_decision_sequence)
        self.event_port.require_activity_storage()
        worker_result = self.event_port.accept_activity(
            event_activity,
            task,
            accepted_at=accepted_at,
            started_at=accepted_at,
        )
        if worker_result is None:
            if _graph_worker_call_marker_committed(
                self.event_port,
                run_id=run_id,
                activity_id=activity.activity_id,
            ):
                raise EventIncompleteHistoryError(
                    "graph Worker call is durable without a recorded result; "
                    "re-execution is forbidden"
                )
            self._record_event(
                HarnessEvent(
                    event_type=HarnessEventType.WORKER_CALLED,
                    run_id=run_id,
                    step_id=step.step_id,
                    payload={
                        **task,
                        "activity_id": activity.activity_id,
                        "idempotency_key": activity.idempotency_key,
                        "activity_attempt": activity.attempt,
                        "activity_contract_version": event_activity.contract_version,
                        "node_instance_id": activity.node_instance_id,
                    },
                    occurred_at=accepted_at,
                )
            )
            binding = self._worker_bindings_by_run.get(run_id, {}).get(step.step_id)
            if is_compensation:
                worker_result = self._execute_graph_compensation(
                    run_spec,
                    current_state,
                    activity,
                    compensation_task,
                )
            else:
                if binding is None or not callable(
                    getattr(binding.implementation, "execute", None)
                ):
                    raise HarnessValidationError(
                        "exact graph Worker binding is unavailable",
                        code="unknown_runtime_worker_binding",
                        details={"step_id": step.step_id},
                    )
                worker_result = _coerce_worker_result(
                    binding.implementation.execute(
                        _task_with_activity(task, event_activity)
                    )
                )
        else:
            worker_result = _coerce_worker_result(worker_result)
        result_event = self.event_port.record_activity_result(
            event_activity,
            worker_result,
            completed_at=_graph_time(run_spec, activity.causal_decision_sequence + 1),
        )
        if not isinstance(result_event, HarnessEvent):
            raise HarnessValidationError(
                "graph Worker result storage returned an invalid event"
            )
        if not any(
            item.event_id == result_event.event_id for item in self._committed_events
        ):
            self._committed_events.append(result_event)
        graph_result_at = _graph_time(
            run_spec,
            activity.causal_decision_sequence + 2,
        )
        if self._graph_result_observer is not None:
            observed_event = self._graph_result_observer.observe_result(
                activity=activity,
                graph=self._prepared_graphs[run_id],
                run_spec_checksum=self._prepared_run_specs[run_id],
                worker_result=worker_result,
                occurred_at=graph_result_at,
            )
            if observed_event is not None:
                if not isinstance(observed_event, HarnessEvent):
                    raise HarnessValidationError(
                        "graph result observer returned an invalid event",
                        code="graph_result_observer_event_invalid",
                    )
                if not any(
                    item.event_id == observed_event.event_id
                    for item in self._committed_events
                ):
                    self._committed_events.append(observed_event)
        if self._graph_result_committer is None:
            payload_ref = checksum_for(worker_result.to_dict())
            graph_result = HarnessGraphActivityResult.for_activity(
                activity,
                evidence_ref=checksum_for(
                    {
                        "activity_id": activity.activity_id,
                        "result_event_id": result_event.event_id,
                        "payload_ref": payload_ref,
                    }
                ),
                payload_ref=payload_ref,
                status=(
                    HarnessGraphActivityResultStatus.FAILED
                    if worker_result.status is HarnessWorkerStatus.FAILED
                    else HarnessGraphActivityResultStatus.SUCCEEDED
                ),
                termination_confirmed=True,
            )
            state = self.accept_graph_activity_result(
                run_spec,
                graph_result,
                occurred_at=graph_result_at,
            )
        else:
            state = self._graph_result_committer.commit_result(
                activity=activity,
                graph=self._prepared_graphs[run_id],
                run_spec_checksum=self._prepared_run_specs[run_id],
                worker_result=worker_result,
                occurred_at=graph_result_at,
            )
            self._validate_materialized_graph_result_commit(
                activity=activity,
                graph=self._prepared_graphs[run_id],
                state=state,
            )
        self._graph_worker_results.setdefault(run_id, {})[activity.node_instance_id] = (
            worker_result
        )
        budget_fact = resolve_harness_cumulative_budget_fact(
            run_id=run_id,
            worker_result=worker_result,
            resolver=self._budget_fact_resolver,
        )
        if budget_fact is not None:
            self._graph_budget_facts.setdefault(run_id, {})[
                activity.node_instance_id
            ] = budget_fact
            self._record_or_validate_budget_fact(
                run_spec,
                activity,
                budget_fact,
            )
        self._record_graph_worker_status(
            run_spec,
            state,
            activity,
            worker_result,
        )

    def _validate_materialized_graph_result_commit(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
    ) -> None:
        if (
            not isinstance(state, HarnessGraphState)
            or state.run_id != activity.run_id
            or state.graph_ref.checksum != graph.checksum
        ):
            raise HarnessValidationError(
                "graph result committer returned an invalid graph state",
                code="graph_result_committer_state_invalid",
            )
        recovery = self._require_graph_runtime().transition_port.recover_graph(
            activity.run_id
        )
        causes = tuple(
            item
            for item in recovery.activity_result_commits
            if item.result.activity_id == activity.activity_id
        )
        if len(causes) != 1 or causes[0].result.result_lineage is None:
            raise HarnessValidationError(
                "graph result committer did not persist exact materialized lineage",
                code="graph_result_committer_lineage_missing",
            )
        cause = causes[0]
        projections = tuple(
            item
            for item in recovery.projection_commits
            if item.commit_kind
            is HarnessGraphCommitKind.ACTIVITY_RESULT_PROJECTION
            and item.cause_checksum == cause.result.result_checksum
            and item.sequence == cause.sequence + 1
        )
        if (
            len(projections) != 1
            or projections[0].state != state
            or recovery.state != state
        ):
            raise HarnessValidationError(
                "graph result committer did not persist the adjacent projection",
                code="graph_result_committer_projection_missing",
            )

    def _record_or_validate_budget_fact(
        self,
        run_spec: HarnessRunSpec,
        activity: HarnessGraphActivity,
        fact: HarnessCumulativeBudgetFact,
    ) -> HarnessEvent:
        step_id = activity.step_ref.contract_id
        expected_payload = fact.control_projection()
        matches = tuple(
            event
            for event in self.event_port.read_history(run_spec.run_id)
            if event.event_type is HarnessEventType.BUDGET_FACT_RECORDED
            and event.step_id == step_id
            and event.payload.get("operation_id") == fact.operation_id
            and event.payload.get("ledger_revision") == fact.ledger_revision
        )
        if matches:
            if len(matches) != 1 or not _budget_fact_payload_matches(
                matches[0].payload,
                expected_payload,
            ):
                raise EventStoreCorruptionError(
                    "durable Harness budget fact conflicts with canonical ledger history"
                )
            return matches[0]
        return self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.BUDGET_FACT_RECORDED,
                run_id=run_spec.run_id,
                step_id=step_id,
                payload=expected_payload,
                metadata={
                    "node_instance_id": activity.node_instance_id,
                    "attempt": activity.attempt,
                },
                occurred_at=_graph_time(
                    run_spec,
                    activity.causal_decision_sequence + 2,
                ),
            )
        )

    def _execute_graph_compensation(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        activity: HarnessGraphActivity,
        compensation_task: Mapping[str, Any],
    ) -> HarnessWorkerResult:
        node = _graph_node_by_instance(state, activity.node_instance_id)
        entry = compensation_entry_for_node(state, node)
        binding_id = compensation_task.get("binding_id")
        resolved = self._resolved_graph_bindings.get(run_spec.run_id)
        binding = (
            None
            if resolved is None or not isinstance(binding_id, str)
            else resolved.compensations_by_binding.get(binding_id)
        )
        if binding is None or binding.reference != entry.handler_ref:
            raise HarnessValidationError(
                "exact compensation handler binding is unavailable",
                code="unknown_runtime_compensation_binding",
                details={"binding_id": binding_id},
            )
        if (
            activity.activity_ref != entry.activity_ref
            or activity.fencing_generation != entry.fencing_generation
            or compensation_task.get("entry_id") != entry.entry_id
            or compensation_task.get("idempotency_key") != entry.idempotency_key
        ):
            raise HarnessValidationError(
                "compensation activity does not match its durable entry",
                code="graph_compensation_binding_mismatch",
            )
        request = {
            "run_id": run_spec.run_id,
            "step_id": node.step_id,
            **dict(compensation_task),
            "attempt": activity.attempt,
            "fencing_generation": activity.fencing_generation,
            "harness_activity": {
                "activity_id": activity.activity_id,
                "activity_idempotency_key": activity.idempotency_key,
                "attempt": activity.attempt,
                "activity_ref": activity.activity_ref.exact_ref,
                "causal_decision_checksum": activity.causal_decision_checksum,
                "fencing_generation": activity.fencing_generation,
            },
        }
        try:
            value = binding.implementation.compensate(request)
            return _coerce_compensation_result(value)
        except Exception as exc:  # noqa: BLE001 - failure becomes durable evidence
            return HarnessWorkerResult(
                HarnessWorkerStatus.FAILED,
                error=f"compensation_handler_failed:{type(exc).__name__}",
            )

    def _record_graph_worker_status(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        activity: HarnessGraphActivity,
        result: HarnessWorkerResult,
    ) -> HarnessGraphState:
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.WORKER_STATUS,
            activity.node_id,
            activity.node_instance_id,
            activity.attempt,
            self._next_graph_sequence(run_spec.run_id),
            activity.worker_ref,
            checksum_for(
                {
                    "activity_result": result.candidate_result_ref,
                    "worker_ref": activity.worker_ref.exact_ref,
                }
            ),
            payload={"status": result.status.value},
        )
        return self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )

    def _graph_scoped_inputs(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        node_instance_id: str,
        input_keys: tuple[str, ...],
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key in input_keys:
            found, value = self._graph_resolve_output(
                run_spec,
                state,
                output_key=key,
                consumer_node_instance_id=node_instance_id,
            )
            values[key] = value if found else run_spec.inputs.get(key)
        return values

    def _graph_scoped_output_projection(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        node_instance_id: str,
    ) -> dict[str, Any]:
        graph = self._prepared_graphs[run_spec.run_id]
        projection: dict[str, Any] = {}
        for key in _graph_declared_output_keys(graph):
            found, value = self._graph_resolve_output(
                run_spec,
                state,
                output_key=key,
                consumer_node_instance_id=node_instance_id,
            )
            if found:
                projection[key] = value
        current = next(
            (
                item
                for item in state.node_instances
                if item.instance_id == node_instance_id
            ),
            None,
        )
        if current is None:
            raise EventIncompleteHistoryError(
                "graph output projection references an unknown node instance"
            )
        definition = _graph_definition_by_id(graph, current.identity.node_id)
        result = self._graph_worker_results.get(run_spec.run_id, {}).get(
            current.instance_id
        )
        if (
            isinstance(definition, HarnessExecutableNode)
            and result is not None
            and result.status is HarnessWorkerStatus.SUCCEEDED
        ):
            for key in definition.output_keys:
                projection[key] = _graph_executable_output_value(
                    definition,
                    result,
                    key,
                )
        return projection

    def _graph_root_output_projection(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> dict[str, Any]:
        graph = self._prepared_graphs[run_spec.run_id]
        projection: dict[str, Any] = {}
        for key in _graph_declared_output_keys(graph):
            found, value = self._graph_resolve_output(
                run_spec,
                state,
                output_key=key,
                consumer_node_instance_id=None,
            )
            if found:
                projection[key] = value
        return projection

    def _graph_resolve_output(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        output_key: str,
        consumer_node_instance_id: str | None,
    ) -> tuple[bool, Any]:
        graph = self._prepared_graphs[run_spec.run_id]
        definitions = {item.node_id: item for item in graph.nodes}
        consumer = (
            None
            if consumer_node_instance_id is None
            else next(
                (
                    item
                    for item in state.node_instances
                    if item.instance_id == consumer_node_instance_id
                ),
                None,
            )
        )
        if consumer_node_instance_id is not None and consumer is None:
            raise EventIncompleteHistoryError(
                "graph input resolution references an unknown consumer node"
            )
        consumer_definition = (
            None if consumer is None else definitions.get(consumer.identity.node_id)
        )
        if consumer is not None and consumer_definition is None:
            raise EventIncompleteHistoryError(
                "graph input resolution cannot resolve the consumer definition"
            )

        distance_cache: dict[tuple[str, str], int | None] = {}

        def distance(source_id: str, target_id: str) -> int | None:
            identity = (source_id, target_id)
            if identity not in distance_cache:
                distance_cache[identity] = _graph_path_distance(
                    graph,
                    source_id,
                    target_id,
                )
            return distance_cache[identity]

        candidates: list[
            tuple[HarnessNodeInstanceState, HarnessGraphNode, int | None]
        ] = []
        for node in state.node_instances:
            if node.status is not HarnessNodeInstanceStatus.SUCCEEDED:
                continue
            definition = definitions.get(node.identity.node_id)
            if definition is None or output_key not in _graph_node_output_keys(
                definition
            ):
                continue
            if not isinstance(node.output_refs.get(output_key), str):
                raise EventIncompleteHistoryError(
                    "successful graph output has no exact payload reference"
                )
            path_distance: int | None = None
            if consumer is not None:
                if (
                    node.identity.activation_ordinal
                    >= consumer.identity.activation_ordinal
                ):
                    continue
                if not _graph_scope_compatible(
                    node.identity.branch_path,
                    consumer.identity.branch_path,
                ) or not _graph_scope_compatible(
                    node.identity.iteration_vector,
                    consumer.identity.iteration_vector,
                ):
                    continue
                assert consumer_definition is not None
                path_distance = distance(
                    definition.node_id,
                    consumer_definition.node_id,
                )
                if path_distance is None:
                    continue
            candidates.append((node, definition, path_distance))
        if not candidates:
            return False, None

        latest_by_definition: dict[
            str,
            tuple[HarnessNodeInstanceState, HarnessGraphNode, int | None],
        ] = {}
        for candidate in candidates:
            node = candidate[0]
            existing = latest_by_definition.get(node.identity.node_id)
            if existing is None or (
                node.identity.activation_ordinal,
                node.last_event_sequence,
                node.instance_id,
            ) > (
                existing[0].identity.activation_ordinal,
                existing[0].last_event_sequence,
                existing[0].instance_id,
            ):
                latest_by_definition[node.identity.node_id] = candidate
        narrowed = tuple(latest_by_definition.values())
        if consumer is not None:
            nearest_distance = min(item[2] for item in narrowed if item[2] is not None)
            selected = tuple(item for item in narrowed if item[2] == nearest_distance)
        else:
            selected = tuple(
                candidate
                for candidate in narrowed
                if not any(
                    _graph_candidate_dominates(
                        other,
                        candidate,
                        distance=distance,
                    )
                    for other in narrowed
                    if other[0].instance_id != candidate[0].instance_id
                )
            )
        if len(selected) != 1:
            if consumer is None:
                return False, None
            raise HarnessValidationError(
                "graph output key has no unique scope-visible producer",
                code="graph_output_producer_ambiguous",
                details={
                    "output_key": output_key,
                    "consumer_node_instance_id": consumer_node_instance_id,
                    "producer_node_instance_ids": sorted(
                        item[0].instance_id for item in selected
                    ),
                },
            )
        producer, definition, _ = selected[0]
        return True, self._graph_output_value(
            run_spec,
            producer,
            definition,
            output_key,
        )

    def _graph_output_value(
        self,
        run_spec: HarnessRunSpec,
        producer: HarnessNodeInstanceState,
        definition: HarnessGraphNode,
        output_key: str,
    ) -> Any:
        worker_results = self._graph_worker_results.get(run_spec.run_id, {})
        if isinstance(definition, HarnessExecutableNode):
            result = worker_results.get(producer.instance_id)
            if result is None:
                raise EventIncompleteHistoryError(
                    "graph output reference has no recoverable Worker result"
                )
            return _graph_executable_output_value(definition, result, output_key)
        if not isinstance(definition, HarnessControlNode) or definition.merge is None:
            raise EventIncompleteHistoryError(
                "graph output producer has no materialization contract"
            )
        if definition.merge.merge_kind is HarnessMergeKind.PURE:
            outputs = producer.metadata.get("merge_outputs")
            if not isinstance(outputs, Mapping) or output_key not in outputs:
                raise EventIncompleteHistoryError(
                    "pure Merge output manifest is missing one declared key"
                )
            return thaw_canonical_json(outputs[output_key])
        aggregation_id = producer.metadata.get("aggregation_node_instance_id")
        result = (
            None
            if not isinstance(aggregation_id, str)
            else worker_results.get(aggregation_id)
        )
        if result is None:
            raise EventIncompleteHistoryError(
                "aggregation Merge output has no recoverable Worker result"
            )
        aggregation_definition = _graph_definition_by_id(
            self._prepared_graphs[run_spec.run_id],
            definition.merge.aggregation_node_id or "",
        )
        if not isinstance(aggregation_definition, HarnessExecutableNode):
            raise EventIncompleteHistoryError(
                "aggregation Merge output definition is invalid"
            )
        return _graph_executable_output_value(
            aggregation_definition,
            result,
            output_key,
        )

    def _graph_worker_task(
        self,
        run_spec: HarnessRunSpec,
        step: HarnessStepSpec,
        outputs: Mapping[str, Any],
        *,
        state: HarnessGraphState | None = None,
        node_instance_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_inputs = (
            {
                key: outputs[key] if key in outputs else run_spec.inputs.get(key)
                for key in step.input_keys
            }
            if state is None or node_instance_id is None
            else self._graph_scoped_inputs(
                run_spec,
                state,
                node_instance_id=node_instance_id,
                input_keys=step.input_keys,
            )
        )
        task = {
            "run_id": run_spec.run_id,
            "step_id": step.step_id,
            "worker_type": step.worker_type.value,
            "inputs": resolved_inputs,
            "metadata": step.metadata,
        }
        if state is None or node_instance_id is None:
            return task
        node = next(
            (
                item
                for item in state.node_instances
                if item.instance_id == node_instance_id
            ),
            None,
        )
        if node is None:
            raise EventIncompleteHistoryError(
                "graph Worker task references an unknown node instance"
            )
        graph = self._prepared_graphs[run_spec.run_id]
        merge_definition = next(
            (
                item
                for item in graph.nodes
                if isinstance(item, HarnessControlNode)
                and item.merge is not None
                and item.merge.aggregation_node_id == node.identity.node_id
            ),
            None,
        )
        if merge_definition is None:
            return task
        branch_inputs_key = merge_definition.metadata.get("branch_inputs_key")
        if not isinstance(branch_inputs_key, str):
            raise EventIncompleteHistoryError(
                "verified aggregation is missing its branch input key"
            )
        _, _, references = merge_branch_output_references(
            graph,
            state,
            merge_definition,
            branch_path=node.identity.branch_path,
            iteration_vector=node.identity.iteration_vector,
        )
        task["inputs"][branch_inputs_key] = tuple(item.to_dict() for item in references)
        return task

    def _graph_activity_task(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        activity: HarnessGraphActivity,
    ) -> dict[str, Any]:
        node = _graph_node_by_instance(state, activity.node_instance_id)
        if any(
            item.compensation_node_instance_id == node.instance_id
            for item in state.compensation_stack
        ):
            return self._graph_compensation_task(run_spec, state, node)
        definition = self._graph_definition(run_spec.run_id, activity.node_id)
        step = self._graph_step(run_spec, definition.step_id)
        return self._graph_worker_task(
            run_spec,
            step,
            self._graph_outputs.setdefault(run_spec.run_id, {}),
            state=state,
            node_instance_id=activity.node_instance_id,
        )

    def _graph_compensation_task(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        node: HarnessNodeInstanceState,
    ) -> dict[str, Any]:
        entry = compensation_entry_for_node(state, node, require_running=False)
        graph = self._prepared_graphs[run_spec.run_id]
        definition = _graph_definition_by_id(graph, node.identity.node_id)
        if not isinstance(definition, HarnessExecutableNode):
            raise EventIncompleteHistoryError(
                "compensation node has no executable definition"
            )
        origin = _graph_node_by_instance(state, entry.origin_node_instance_id)
        bindings = tuple(
            item
            for item in graph.compensation_refs
            if item.for_node_id == origin.identity.node_id
            and item.compensation_node_id == definition.node_id
            and item.handler_ref == entry.handler_ref
            and item.activity_ref == entry.activity_ref
        )
        if len(bindings) != 1:
            raise EventIncompleteHistoryError(
                "compensation entry has no unique pinned graph binding"
            )
        binding = bindings[0]
        step = self._graph_step(run_spec, definition.step_id)
        return {
            "run_id": run_spec.run_id,
            "step_id": step.step_id,
            "worker_type": step.worker_type.value,
            "inputs": {},
            "metadata": step.metadata,
            "compensation": {
                "binding_id": binding.binding_id,
                "entry_id": entry.entry_id,
                "origin_node_instance_id": entry.origin_node_instance_id,
                "effect_outcome_ref": entry.effect_outcome_ref,
                "effect_commit_sequence": entry.effect_commit_sequence,
                "handler_ref": entry.handler_ref.exact_ref,
                "activity_ref": entry.activity_ref.exact_ref,
                "idempotency_key": entry.idempotency_key,
                "tenant_scope_ref": state.metadata.get("tenant_scope_ref"),
                "identity_scope_ref": state.metadata.get("identity_scope_ref"),
                "subject_scope_ref": state.metadata.get("subject_scope_ref"),
            },
        }

    def _graph_activity_input_ref(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        decision: HarnessGraphDecision,
    ) -> str:
        if decision.node_id is None:
            raise HarnessValidationError(
                "graph activity decision is missing a node definition"
            )
        definition = self._graph_definition(run_spec.run_id, decision.node_id)
        step = self._graph_step(run_spec, definition.step_id)
        node = _graph_node_by_instance(state, decision.node_instance_id or "")
        if node.status is HarnessNodeInstanceStatus.COMPENSATING:
            task = self._graph_compensation_task(run_spec, state, node)
        else:
            task = self._graph_worker_task(
                run_spec,
                step,
                self._graph_outputs.setdefault(run_spec.run_id, {}),
                state=state,
                node_instance_id=decision.node_instance_id,
            )
        return harness_activity_input_checksum(task)

    def _graph_evaluation_context(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        recovery,
        *,
        through_sequence: int | None = None,
    ) -> HarnessGraphEvaluationContext:
        replay_limit = (
            recovery.expected_last_sequence
            if through_sequence is None
            else through_sequence
        )
        instances = {item.instance_id: item for item in state.node_instances}
        latest: dict[tuple[str, int, str, str], HarnessAcceptedGraphObservation] = {}
        for commit in recovery.observation_commits:
            if commit.sequence > replay_limit:
                continue
            observation = commit.observation
            if observation.observation_type in {
                HarnessGraphObservationType.MERGE_RESULT,
                HarnessGraphObservationType.WAIT_CAUSE,
                HarnessGraphObservationType.RUN_OPERATION,
            }:
                continue
            instance = instances.get(observation.node_instance_id)
            if instance is None or observation.attempt != instance.attempt:
                continue
            definition = next(
                (
                    item
                    for item in self._prepared_graphs[state.run_id].nodes
                    if item.node_id == observation.node_id
                ),
                None,
            )
            if (
                observation.observation_type is HarnessGraphObservationType.GATE_RESULT
                and (
                    not isinstance(definition, HarnessExecutableNode)
                    or observation.contract_ref not in definition.gate_refs
                )
            ):
                continue
            identity = (
                observation.node_instance_id,
                observation.attempt,
                observation.observation_type.value,
                (
                    observation.contract_ref.exact_ref
                    if observation.observation_type
                    is HarnessGraphObservationType.GATE_RESULT
                    else ""
                ),
            )
            latest[identity] = observation
        return HarnessGraphEvaluationContext(
            inputs=run_spec.inputs,
            observations=tuple(
                sorted(
                    latest.values(),
                    key=lambda item: (
                        item.event_sequence,
                        item.node_instance_id,
                        item.observation_type.value,
                    ),
                )
            ),
        )

    def _graph_step_inputs(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        recovery,
        *,
        through_sequence: int | None = None,
        worker_results_by_attempt: Mapping[tuple[str, int], HarnessWorkerResult]
        | None = None,
    ) -> tuple[HarnessGraphStepSchedulingInput, ...]:
        inputs: list[HarnessGraphStepSchedulingInput] = []
        compensation_mode = state.metadata.get("execution_mode") == "compensating"
        for node in state.node_instances:
            if (
                compensation_mode
                and node.status is not HarnessNodeInstanceStatus.COMPENSATING
            ):
                continue
            if (
                node.node_kind is not HarnessGraphNodeKind.EXECUTABLE
                or node.status
                not in {
                    HarnessNodeInstanceStatus.READY,
                    HarnessNodeInstanceStatus.RUNNING,
                    HarnessNodeInstanceStatus.COMPENSATING,
                }
            ):
                if not (
                    node.status is HarnessNodeInstanceStatus.WAITING
                    and node.step_status is HarnessStepStatus.WAITING_APPROVAL
                    and node.metadata.get("approval_granted") is True
                    and any(
                        evidence.kind is HarnessEvidenceKind.APPROVAL
                        and evidence.attempt == node.attempt
                        for evidence in node.evidence_refs
                    )
                ):
                    continue
            step = self._graph_step(run_spec, node.step_id or "")
            inputs.append(
                HarnessGraphStepSchedulingInput(
                    node.instance_id,
                    step,
                    self._graph_step_observations(
                        state,
                        node,
                        recovery,
                        through_sequence=through_sequence,
                        worker_results_by_attempt=worker_results_by_attempt,
                    ),
                    self._graph_step_budget(run_spec, state),
                )
            )
        return tuple(inputs)

    def _graph_step_observations(
        self,
        state: HarnessGraphState,
        node: HarnessNodeInstanceState,
        recovery,
        *,
        through_sequence: int | None = None,
        worker_results_by_attempt: Mapping[tuple[str, int], HarnessWorkerResult]
        | None = None,
    ) -> StepLifecycleObservations:
        replay_limit = (
            recovery.expected_last_sequence
            if through_sequence is None
            else through_sequence
        )
        worker_result = (
            self._graph_worker_results.get(state.run_id, {}).get(node.instance_id)
            if worker_results_by_attempt is None
            else worker_results_by_attempt.get((node.instance_id, node.attempt))
        )
        worker_observation = None
        if worker_result is not None and node.attempt > 0:
            activity_evidence = max(
                (
                    item
                    for item in node.evidence_refs
                    if item.kind is HarnessEvidenceKind.ACTIVITY_RESULT
                    and item.attempt == node.attempt
                    and item.contract_ref is not None
                    and item.contract_ref.contract_kind is HarnessContractKind.ACTIVITY
                ),
                key=lambda item: item.event_sequence,
                default=None,
            )
            if activity_evidence is None:
                raise EventIncompleteHistoryError(
                    "graph Worker result is missing accepted activity evidence"
                )
            worker_observation = StepWorkerObservation.from_worker_result(
                worker_result,
                accepted_evidence=activity_evidence,
                cumulative_budget_fact=self._graph_budget_facts.get(
                    state.run_id,
                    {},
                ).get(node.instance_id),
            )

        approval_evidence = max(
            (
                item
                for item in node.evidence_refs
                if item.kind is HarnessEvidenceKind.APPROVAL
                and item.attempt == node.attempt
            ),
            key=lambda item: item.event_sequence,
            default=None,
        )

        boundary = self._graph_phase_boundary_sequence(
            node,
            recovery,
            through_sequence=replay_limit,
        )
        gate_observations: list[StepGateObservation] = []
        quality_observation: StepQualityObservation | None = None
        if boundary is not None:
            latest_gate: dict[str, HarnessAcceptedGraphObservation] = {}
            latest_quality: HarnessAcceptedGraphObservation | None = None
            for commit in recovery.observation_commits:
                if commit.sequence > replay_limit:
                    continue
                observation = commit.observation
                if (
                    observation.node_instance_id != node.instance_id
                    or observation.attempt != node.attempt
                    or observation.event_sequence <= boundary
                ):
                    continue
                if (
                    observation.observation_type
                    is HarnessGraphObservationType.GATE_RESULT
                ):
                    latest_gate[observation.contract_ref.exact_ref] = observation
                elif (
                    observation.observation_type
                    is HarnessGraphObservationType.QUALITY_VERDICT
                ):
                    latest_quality = observation
            for observation in latest_gate.values():
                evidence = _graph_evidence_for_observation(node, observation)
                gate_observations.append(
                    StepGateObservation(
                        gate_name=observation.contract_ref.contract_id,
                        passed=bool(observation.payload["passed"]),
                        gate_reference=observation.contract_ref.exact_ref,
                        input_ref=str(observation.payload["input_ref"]),
                        result_ref=str(observation.payload["result_ref"]),
                        gate_reason_code=str(observation.payload["reason_code"]),
                        accepted_evidence=evidence,
                    )
                )
            if latest_quality is not None:
                quality_observation = StepQualityObservation(
                    passed=bool(latest_quality.payload["passed"]),
                    score=latest_quality.payload["score"],
                    accepted_evidence=_graph_evidence_for_observation(
                        node,
                        latest_quality,
                    ),
                )
        return StepLifecycleObservations.for_node(
            node,
            worker_result=worker_observation,
            gate_results=tuple(gate_observations),
            quality_verdict=quality_observation,
            approval_granted=(
                approval_evidence is not None
                and node.metadata.get("approval_granted") is True
            ),
            approval_evidence=approval_evidence,
        )

    @staticmethod
    def _graph_phase_boundary_sequence(
        node: HarnessNodeInstanceState,
        recovery,
        *,
        through_sequence: int | None = None,
    ) -> int | None:
        expected_type = {
            HarnessStepStatus.PLANNING: HarnessGraphDecisionType.ENTER_STEP_PHASE,
            HarnessStepStatus.VERIFYING: HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        }.get(node.step_status)
        if expected_type is None:
            return None
        commits = tuple(
            item
            for item in recovery.decision_commits
            if item.decision.node_instance_id == node.instance_id
            and item.decision.decision_type is expected_type
            and (through_sequence is None or item.sequence <= through_sequence)
        )
        return None if not commits else commits[-1].sequence

    @staticmethod
    def _graph_step_budget(
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> StepLifecycleBudget:
        return StepLifecycleBudget(
            max_turns=run_spec.budget.max_turns,
            turns_used=state.budgets.require("turns").used,
            max_replans=run_spec.budget.max_replans,
            replans_used=state.budgets.require("replans").used,
            max_retries_per_step=run_spec.budget.max_retries_per_step,
            max_worker_calls=run_spec.budget.max_worker_calls,
            worker_calls_used=state.budgets.require("worker_calls").used,
            halt_on_budget_exceeded=run_spec.budget.halt_on_budget_exceeded,
        )

    def _run_graph_plan_gates(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str | None,
        *,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessGraphState:
        if step_id is None:
            raise HarnessValidationError("PLAN decision is missing its Step binding")
        results = self._evaluate_graph_gates(
            run_spec,
            state,
            step_id,
            tuple((_gate_reference(gate), gate) for gate in self.plan_gates),
            worker_result=worker_result,
        )
        # Passing plan gates are summarized by the committed PLAN phase. A
        # failure is projected as exact evidence because it changes the next
        # Scheduler decision (replan or halt).
        if all(result.passed for result in results):
            return state
        return self._accept_graph_gate_results(
            run_spec,
            state,
            step_id,
            results,
        )

    def _run_graph_verify_gates(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str | None,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessGraphState:
        if step_id is None:
            raise HarnessValidationError("VERIFY decision is missing its Step binding")
        entries = self._graph_verify_gate_entries(run_spec, state, step_id)
        results = self._evaluate_graph_gates(
            run_spec,
            state,
            step_id,
            entries,
            worker_result=worker_result,
        )
        state = self._accept_graph_gate_results(
            run_spec,
            state,
            step_id,
            results,
        )
        return self._accept_graph_verify_verdict(
            run_spec,
            state,
            step_id,
            results,
        )

    def _graph_verify_gate_entries(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str,
    ) -> tuple[tuple[str, DeterministicGate], ...]:
        entries: list[tuple[str, DeterministicGate]] = [
            (_gate_reference(gate), gate) for gate in self.verify_gates
        ]
        node = _graph_node_for_step(state, step_id)
        cumulative_budget_fact = self._graph_budget_facts.get(
            run_spec.run_id,
            {},
        ).get(node.instance_id)
        if cumulative_budget_fact is None:
            # The cumulative ledger is opt-in at the worker boundary. Keep
            # legacy graph runs byte-for-byte compatible until a durable fact
            # is actually available for deterministic verification.
            entries = [
                (reference, gate)
                for reference, gate in entries
                if not isinstance(gate, CumulativeLLMBudgetGate)
            ]
        entries.extend(
            (str(binding.reference), binding.gate)
            for binding in self._gate_bindings_by_run.get(
                run_spec.run_id,
                {},
            ).get(step_id, ())
        )
        deduplicated: list[tuple[str, DeterministicGate]] = []
        seen: set[str] = set()
        for reference, gate in entries:
            if reference in seen:
                continue
            seen.add(reference)
            deduplicated.append((reference, gate))
        return tuple(deduplicated)

    def _accept_graph_verify_verdict(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str,
        results: tuple[HarnessGateResult, ...],
    ) -> HarnessGraphState:
        step = self._graph_step(run_spec, step_id)
        verdict = aggregate_gate_verdict(
            results,
            declared_gate_reference=step.quality_gate,
        )
        node = _graph_node_for_step(state, step_id)
        self._graph_gate_results.setdefault(run_spec.run_id, {})[node.instance_id] = (
            results
        )
        if verdict is not None:
            state = self._accept_graph_quality_verdict(
                run_spec,
                state,
                node.instance_id,
                verdict,
            )
            self._graph_quality_verdicts.setdefault(run_spec.run_id, {})[
                node.instance_id
            ] = verdict
        return state

    def _reconcile_graph_verify_gates(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        recovery,
    ) -> HarnessGraphState:
        verifying_nodes = tuple(
            sorted(
                (
                    node
                    for node in state.node_instances
                    if node.node_kind is HarnessGraphNodeKind.EXECUTABLE
                    and node.status
                    in {
                        HarnessNodeInstanceStatus.RUNNING,
                        HarnessNodeInstanceStatus.COMPENSATING,
                    }
                    and node.step_status is HarnessStepStatus.VERIFYING
                ),
                key=lambda node: (
                    node.identity.activation_ordinal,
                    node.instance_id,
                ),
            )
        )
        for node in verifying_nodes:
            boundary = self._graph_phase_boundary_sequence(node, recovery)
            if boundary is None:
                raise EventIncompleteHistoryError(
                    "verifying Graph node lacks its durable VERIFY decision"
                )
            step_id = node.step_id
            if step_id is None:
                raise EventIncompleteHistoryError(
                    "verifying Graph node lacks its Step binding"
                )
            entries = self._graph_verify_gate_entries(run_spec, state, step_id)
            observations = tuple(
                commit.observation
                for commit in recovery.observation_commits
                if commit.observation.node_instance_id == node.instance_id
                and commit.observation.attempt == node.attempt
                and commit.observation.event_sequence > boundary
            )
            gate_observations = {
                observation.contract_ref.exact_ref: observation
                for observation in observations
                if observation.observation_type
                is HarnessGraphObservationType.GATE_RESULT
            }
            quality_observations = tuple(
                observation
                for observation in observations
                if observation.observation_type
                is HarnessGraphObservationType.QUALITY_VERDICT
            )
            missing_entries = tuple(
                (reference, gate)
                for reference, gate in entries
                if reference not in gate_observations
            )
            if missing_entries and quality_observations:
                raise EventStoreCorruptionError(
                    "Graph quality verdict precedes required gate evidence"
                )

            existing_results = {
                reference: _graph_gate_result_from_observation(observation)
                for reference, observation in gate_observations.items()
            }
            if missing_entries:
                worker_result = self._graph_worker_results.get(
                    run_spec.run_id,
                    {},
                ).get(node.instance_id)
                if worker_result is None:
                    raise EventIncompleteHistoryError(
                        "verifying Graph node lacks its durable Worker result"
                    )
                new_results = self._evaluate_graph_gates(
                    run_spec,
                    state,
                    step_id,
                    missing_entries,
                    worker_result=worker_result,
                )
                state = self._accept_graph_gate_results(
                    run_spec,
                    state,
                    step_id,
                    new_results,
                )
                existing_results.update(
                    {
                        str(gate_result_evidence(result)["reference"]): result
                        for result in new_results
                    }
                )

            ordered_results = tuple(
                existing_results[reference]
                for reference, _gate in entries
                if reference in existing_results
            )
            if len(ordered_results) != len(entries):
                raise EventIncompleteHistoryError(
                    "verifying Graph node has incomplete deterministic gate evidence"
                )
            self._graph_gate_results.setdefault(run_spec.run_id, {})[
                node.instance_id
            ] = ordered_results
            step = self._graph_step(run_spec, step_id)
            if step.quality_gate is not None and not quality_observations:
                state = self._accept_graph_verify_verdict(
                    run_spec,
                    state,
                    step_id,
                    ordered_results,
                )
            if missing_entries or (
                step.quality_gate is not None and not quality_observations
            ):
                return state
        return state

    def _evaluate_graph_gates(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str,
        entries: tuple[tuple[str, DeterministicGate], ...],
        *,
        worker_result: HarnessWorkerResult | None,
    ) -> tuple[HarnessGateResult, ...]:
        node = _graph_node_for_step(state, step_id)
        compatibility = self._graph_compat_state(
            run_spec,
            state,
            step_id=step_id,
            outputs=self._graph_scoped_output_projection(
                run_spec,
                state,
                node_instance_id=node.instance_id,
            ),
            worker_result=worker_result,
        )
        step = self._graph_step(run_spec, step_id)
        context = GateContext(
            state=compatibility,
            step_spec=step,
            step_state=get_step_state(compatibility, step_id),
            worker_result=worker_result,
            quality_verdict=None,
            budget=self._graph_budget_snapshot(run_spec, state),
            cumulative_budget_fact=self._graph_budget_facts.get(
                run_spec.run_id,
                {},
            ).get(node.instance_id),
        )
        results = tuple(
            self._evaluate_gate(gate, reference=reference, context=context)
            for reference, gate in entries
        )
        for result in results:
            self._record_event(
                HarnessEvent(
                    event_type=HarnessEventType.GATE_EVALUATED,
                    run_id=run_spec.run_id,
                    step_id=step_id,
                    payload=result.to_dict(),
                    metadata={
                        "node_instance_id": node.instance_id,
                        "attempt": node.attempt,
                    },
                    occurred_at=_graph_time(
                        run_spec,
                        state.last_event_sequence + 1,
                    ),
                )
            )
        return results

    def _accept_graph_gate_results(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        step_id: str,
        results: tuple[HarnessGateResult, ...],
    ) -> HarnessGraphState:
        node = _graph_node_for_step(state, step_id)
        for result in results:
            evidence = gate_result_evidence(result)
            reference = GateReference.parse(str(evidence["reference"]))
            observation = HarnessAcceptedGraphObservation(
                HarnessGraphObservationType.GATE_RESULT,
                node.identity.node_id,
                node.instance_id,
                node.attempt,
                self._next_graph_sequence(run_spec.run_id),
                HarnessContractReference(
                    HarnessContractKind.GATE,
                    reference.gate_id,
                    reference.version,
                ),
                str(evidence["result_ref"]),
                payload={
                    "passed": bool(evidence["passed"]),
                    "input_ref": str(evidence["input_ref"]),
                    "result_ref": str(evidence["result_ref"]),
                    "reason_code": str(evidence["reason_code"]),
                },
            )
            state = self.accept_graph_observation(
                run_spec,
                observation,
                occurred_at=_graph_time(run_spec, observation.event_sequence),
            )
            node = _graph_node_by_instance(state, node.instance_id)
        return state

    def _accept_graph_quality_verdict(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        node_instance_id: str,
        verdict: HarnessQualityVerdict,
    ) -> HarnessGraphState:
        node = _graph_node_by_instance(state, node_instance_id)
        definition = self._graph_definition(
            run_spec.run_id,
            node.identity.node_id,
        )
        step = self._graph_step(run_spec, definition.step_id)
        if step.quality_gate is None:
            return state
        reference = GateReference.parse(step.quality_gate)
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.QUALITY_VERDICT,
            definition.node_id,
            node.instance_id,
            node.attempt,
            self._next_graph_sequence(run_spec.run_id),
            HarnessContractReference(
                HarnessContractKind.GATE,
                reference.gate_id,
                reference.version,
            ),
            checksum_for(verdict.to_dict()),
            payload={"passed": verdict.passed, "score": verdict.score},
        )
        return self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )

    @staticmethod
    def _graph_budget_snapshot(
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
    ) -> HarnessBudgetSnapshot:
        return HarnessBudgetSnapshot.from_budget(
            run_spec.budget,
            turns_used=state.budgets.require("turns").used,
            replans_used=state.budgets.require("replans").used,
            worker_calls_used=state.budgets.require("worker_calls").used,
        )

    def _record_graph_verified_output(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        node_instance_id: str | None,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessGraphState:
        if node_instance_id is None or worker_result is None:
            return state
        node = _graph_node_by_instance(state, node_instance_id)
        if node.status is not HarnessNodeInstanceStatus.SUCCEEDED:
            return state
        definition = self._graph_definition(
            run_spec.run_id,
            node.identity.node_id,
        )
        step_metadata = definition.metadata.get("step_metadata", {})
        raw_paths = (
            step_metadata.get("control_fact_paths", ())
            if isinstance(step_metadata, Mapping)
            else ()
        )
        control_paths = tuple(sorted(str(item) for item in raw_paths))
        if not control_paths:
            return state
        payload = _project_graph_control_facts(worker_result.output, control_paths)
        observation = HarnessAcceptedGraphObservation(
            HarnessGraphObservationType.VERIFIED_OUTPUT,
            definition.node_id,
            node.instance_id,
            node.attempt,
            self._next_graph_sequence(run_spec.run_id),
            definition.step_ref,
            checksum_for(
                {
                    "node_instance_id": node.instance_id,
                    "attempt": node.attempt,
                    "verified_output": payload,
                }
            ),
            payload=payload,
            control_fact_paths=control_paths,
        )
        return self.accept_graph_observation(
            run_spec,
            observation,
            occurred_at=_graph_time(run_spec, observation.event_sequence),
        )

    def _record_graph_phase(
        self,
        run_spec: HarnessRunSpec,
        step_id: str | None,
        phase: HarnessPhase,
        boundary: HarnessPhaseBoundary,
        state: HarnessGraphState,
    ) -> None:
        if step_id is None:
            return
        node = _graph_node_for_step(state, step_id)
        gate_results = self._graph_gate_results.get(run_spec.run_id, {}).get(
            node.instance_id,
            (),
        )
        record = HarnessPhaseRecord(
            phase=phase,
            step_id=step_id,
            boundary=boundary,
            gate_results=tuple(item.to_dict() for item in gate_results),
            metadata={
                "node_instance_id": node.instance_id,
                "attempt": node.attempt,
                "turn_count": state.budgets.require("turns").used,
                "worker_call_count": state.budgets.require("worker_calls").used,
            },
            occurred_at=_graph_time(run_spec, state.last_event_sequence),
        )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id=run_spec.run_id,
                step_id=step_id,
                payload=record.to_dict(),
                occurred_at=record.occurred_at,
            )
        )

    def _graph_compat_state(
        self,
        run_spec: HarnessRunSpec,
        state: HarnessGraphState,
        *,
        step_id: str | None,
        outputs: Mapping[str, Any],
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessState:
        latest_by_step: dict[str, HarnessNodeInstanceState] = {}
        for node in state.node_instances:
            if node.step_id is None:
                continue
            previous = latest_by_step.get(node.step_id)
            if previous is None or (
                node.identity.activation_ordinal,
                node.last_event_sequence,
            ) > (
                previous.identity.activation_ordinal,
                previous.last_event_sequence,
            ):
                latest_by_step[node.step_id] = node
        updated_at = _graph_time(run_spec, state.last_event_sequence)
        step_states: list[HarnessStepState] = []
        for step in run_spec.workflow.steps:
            node = latest_by_step.get(step.step_id)
            result = (
                None
                if node is None
                else self._graph_worker_results.get(run_spec.run_id, {}).get(
                    node.instance_id
                )
            )
            metadata: dict[str, Any] = {}
            if node is not None:
                metadata["node_instance_id"] = node.instance_id
            if result is not None:
                metadata["worker_result"] = result.to_dict()
            if node is not None and "approval_granted" in node.metadata:
                metadata["approval_granted"] = node.metadata["approval_granted"]
            if node is not None and "approval_evidence_ref" in node.metadata:
                metadata["approval_evidence_ref"] = node.metadata[
                    "approval_evidence_ref"
                ]
            metadata.update(
                self._graph_side_effect_metadata(run_spec.run_id, step.step_id)
            )
            step_states.append(
                HarnessStepState(
                    step_id=step.step_id,
                    status=(
                        HarnessStepStatus.PENDING
                        if node is None or node.step_status is None
                        else node.step_status
                    ),
                    attempts=0 if node is None else node.attempt,
                    replans=0 if node is None else node.replans,
                    output_ref=(
                        step.output_key
                        if node is not None
                        and node.status is HarnessNodeInstanceStatus.SUCCEEDED
                        else None
                    ),
                    error=(
                        None
                        if node is None
                        else node.terminal_reason or node.error_code
                    ),
                    metadata=metadata,
                    updated_at=updated_at,
                )
            )
        blocked_by_worker = any(
            item.status is HarnessNodeInstanceStatus.WAITING
            and item.metadata.get("worker_blocked") is True
            for item in state.node_instances
        )
        waiting_for_approval = any(
            item.status is HarnessNodeInstanceStatus.WAITING
            and item.metadata.get("worker_blocked") is not True
            for item in state.node_instances
        )
        status = project_public_legacy_status(
            state.lifecycle,
            state.outcome,
            waiting_for_approval=(
                waiting_for_approval and state.lifecycle is RunLifecycle.WAITING
            ),
        )
        if state.lifecycle is RunLifecycle.RUNNING and waiting_for_approval:
            status = HarnessRunStatus.WAITING_APPROVAL
        if state.lifecycle is RunLifecycle.WAITING and blocked_by_worker:
            status = HarnessRunStatus.BLOCKED
        current_step_id = step_id
        if current_step_id is None:
            active_steps = tuple(
                item.step_id
                for item in state.node_instances
                if item.step_id is not None and not item.is_terminal
            )
            current_step_id = active_steps[0] if len(active_steps) == 1 else None
        if current_step_id is None and latest_by_step:
            current_step_id = max(
                latest_by_step.values(),
                key=lambda item: item.identity.activation_ordinal,
            ).step_id
        metadata = {
            **run_spec.metadata,
            "outputs": dict(outputs),
            "graph_id": state.graph_ref.graph_id,
            "graph_version": state.graph_ref.identity_version,
            "graph_checksum": state.graph_ref.checksum,
            "graph_lifecycle": state.lifecycle.value,
            "graph_outcome": state.outcome.value,
            "terminal_reason": _graph_compat_terminal_reason(
                state.terminal_reason_code,
                outcome=state.outcome,
            ),
        }
        terminal_outcome = self._side_effect_outcomes.get(run_spec.run_id, {}).get(
            "__terminal__"
        )
        if state.outcome is RunOutcome.SUCCEEDED and terminal_outcome is not None:
            metadata.update(
                {
                    "terminal_side_effect_effect_ref": checksum_for(
                        terminal_outcome.effect_id
                    ),
                    "terminal_side_effect_decision_ref": terminal_outcome.decision_ref,
                    "terminal_side_effect_outcome_ref": terminal_outcome.checksum,
                    "terminal_side_effect_disposition": (
                        terminal_outcome.disposition.value
                    ),
                }
            )
        if worker_result is not None and current_step_id is not None:
            metadata["current_worker_result_ref"] = worker_result.candidate_result_ref
        return HarnessState(
            run_spec=run_spec,
            status=status,
            step_states=tuple(step_states),
            current_step_id=current_step_id,
            turn_count=state.budgets.require("turns").used,
            replan_count=state.budgets.require("replans").used,
            worker_call_count=state.budgets.require("worker_calls").used,
            metadata=metadata,
            updated_at=updated_at,
        )

    def _graph_side_effect_metadata(
        self,
        run_id: str,
        step_id: str,
    ) -> dict[str, Any]:
        outcome = self._side_effect_outcomes.get(run_id, {}).get(step_id)
        if outcome is None:
            return {}
        metadata: dict[str, Any] = {
            "side_effect_effect_ref": checksum_for(outcome.effect_id),
            "side_effect_decision_ref": outcome.decision_ref,
            "side_effect_outcome_ref": outcome.checksum,
            "side_effect_disposition": outcome.disposition.value,
        }
        if self.side_effect_store is None:
            return metadata
        decisions = tuple(
            item
            for item in self.side_effect_store.list_decisions(run_id=run_id)
            if item.origin is HarnessSideEffectOrigin.WORKER
            and item.step_id == step_id
            and item.checksum == outcome.decision_ref
        )
        if len(decisions) != 1:
            raise EventStoreCorruptionError(
                "durable Graph side-effect outcome has no unique authorization"
            )
        authorization = decisions[0]
        metadata.update(
            {
                "approval_evidence_ref": authorization.approval_evidence_ref,
                "side_effect_intent_ref": authorization.intent_ref,
            }
        )
        return metadata

    def _graph_definition(
        self,
        run_id: str,
        node_id: str,
    ) -> HarnessExecutableNode:
        definition = next(
            (
                item
                for item in self._prepared_graphs[run_id].nodes
                if item.node_id == node_id
            ),
            None,
        )
        if not isinstance(definition, HarnessExecutableNode):
            raise HarnessValidationError(
                "graph executable definition is unavailable",
                code="graph_step_decision_node_kind_mismatch",
                details={"node_id": node_id},
            )
        return definition

    @staticmethod
    def _graph_step(
        run_spec: HarnessRunSpec,
        step_id: str,
    ) -> HarnessStepSpec:
        step = next(
            (item for item in run_spec.workflow.steps if item.step_id == step_id),
            None,
        )
        if step is None:
            raise HarnessValidationError(
                "graph Step definition is unavailable",
                code="graph_step_scheduling_binding_mismatch",
                details={"step_id": step_id},
            )
        return step

    def _graph_step_id(
        self, graph: NormalizedHarnessGraph, node_id: str | None
    ) -> str | None:
        if node_id is None:
            return None
        definition = next(
            (item for item in graph.nodes if item.node_id == node_id), None
        )
        return (
            definition.step_id
            if isinstance(definition, HarnessExecutableNode)
            else None
        )

    def _graph_worker_for_decision(
        self,
        run_id: str,
        node_instance_id: str | None,
    ) -> HarnessWorkerResult | None:
        if node_instance_id is None:
            return None
        return self._graph_worker_results.get(run_id, {}).get(node_instance_id)

    def _graph_gate_results_for_step(
        self,
        run_id: str,
        node_instance_id: str | None,
    ) -> tuple[HarnessGateResult, ...]:
        if node_instance_id is None:
            return ()
        return self._graph_gate_results.get(run_id, {}).get(node_instance_id, ())

    def _graph_quality_verdict_for_step(
        self,
        run_id: str,
        node_instance_id: str | None,
    ) -> HarnessQualityVerdict | None:
        if node_instance_id is None:
            return None
        return self._graph_quality_verdicts.get(run_id, {}).get(node_instance_id)

    @staticmethod
    def _graph_side_effect_input(
        decision: HarnessGraphDecision,
        *,
        command_ordinal: int,
    ) -> dict[str, Any]:
        return {
            "command_ordinal": command_ordinal,
            "causation_id": decision.decision_checksum,
            "graph_projection_checksum": decision.input_projection_checksum,
        }


    def run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        state = self.initialize_graph(run_spec)
        self._ensure_graph_run_created(run_spec)
        return self._drive_graph(run_spec, state)

    def recover_and_run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        if self.graph_transition_port is None:
            raise HarnessValidationError(
                "Harness Graph recovery requires a graph transition port",
                code="graph_transition_port_missing",
            )
        graph_recovery = self.graph_transition_port.recover_graph(run_spec.run_id)
        if graph_recovery.state is None:
            raise EventIncompleteHistoryError(
                "Harness run has no committed Graph state; legacy execution "
                "recovery is forbidden"
            )
        self._prepare_run_spec(run_spec, recovery_only=True)
        state = self.recover_graph(run_spec)
        self._ensure_graph_run_created(run_spec)
        return self._drive_graph(run_spec, state)

    def _ensure_graph_run_created(self, run_spec: HarnessRunSpec) -> None:
        created = tuple(
            event
            for event in self.event_port.read_history(run_spec.run_id)
            if event.event_type is HarnessEventType.RUN_CREATED
        )
        if len(created) > 1:
            raise EventStoreCorruptionError(
                "Graph run history contains duplicate RUN_CREATED events"
            )
        if created:
            if created[0].occurred_at != run_spec.created_at:
                raise EventReplayMismatchError(
                    sequence=0,
                    reason="Graph RUN_CREATED time conflicts with the run specification",
                )
            return
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_spec.run_id,
                metadata={
                    "workflow_id": run_spec.workflow.workflow_id,
                    "workflow_version": run_spec.workflow.workflow_version,
                },
                occurred_at=run_spec.created_at,
            )
        )

    def resume_after_approval(
        self,
        state: HarnessState | HarnessRunSpec,
        *,
        approved: bool,
        reason: str | None = None,
        approval_ref: str | None = None,
    ) -> HarnessRunResult:
        """Durably resume or cancel one approval-waiting Harness projection."""

        if isinstance(state, HarnessRunSpec):
            supplied_state = None
            run_spec = state
        elif isinstance(state, HarnessState):
            supplied_state = state
            run_spec = state.run_spec
        else:
            raise TypeError("state must be HarnessState or HarnessRunSpec")
        self._prepare_run_spec(run_spec)
        if self.graph_transition_port is not None:
            graph_recovery = self.graph_transition_port.recover_graph(run_spec.run_id)
            if graph_recovery.state is not None:
                return self._resume_graph_after_approval(
                    run_spec,
                    supplied_state=supplied_state,
                    approved=approved,
                    reason=reason,
                    approval_ref=approval_ref,
                )
        raise EventIncompleteHistoryError(
            "Harness approval resume requires committed Graph state; legacy "
            "execution recovery is forbidden"
        )

    def _resume_graph_after_approval(
        self,
        run_spec: HarnessRunSpec,
        *,
        supplied_state: HarnessState | None,
        approved: bool,
        reason: str | None,
        approval_ref: str | None,
    ) -> HarnessRunResult:
        state = self.recover_graph(run_spec)
        self._hydrate_graph_execution(run_spec, state)
        self._restore_graph_auxiliary_recovery(run_spec)
        waiting = tuple(
            (node, registration)
            for registration in state.wait_registrations
            if registration.kind.value == "approval" and registration.unresolved
            for node in state.node_instances
            if node.instance_id == registration.node_instance_id
            and node.status is HarnessNodeInstanceStatus.WAITING
            and (
                node.node_kind is HarnessGraphNodeKind.WAIT
                or node.step_status is HarnessStepStatus.WAITING_APPROVAL
            )
        )
        if len(waiting) != 1:
            raise HarnessValidationError("Harness run is not waiting for approval")
        node, registration = waiting[0]
        step = None
        if node.node_kind is HarnessGraphNodeKind.EXECUTABLE:
            if node.step_id is None:
                raise EventIncompleteHistoryError(
                    "approval-waiting Graph node is missing its Step identity"
                )
            step = self._graph_step(run_spec, node.step_id)
            if step.metadata.get("approval_required") is not True:
                raise HarnessValidationError(
                    "approval-waiting Graph node has no pinned approval policy",
                    code="graph_approval_policy_missing",
                )
            compatibility = self._graph_compat_state(
                run_spec,
                state,
                step_id=node.step_id,
                outputs=self._graph_scoped_output_projection(
                    run_spec,
                    state,
                    node_instance_id=node.instance_id,
                ),
                worker_result=None,
            )
            if supplied_state is not None and (
                _approval_resume_projection_checksum(supplied_state)
                != _approval_resume_projection_checksum(compatibility)
            ):
                raise EventReplayMismatchError(
                    sequence=state.last_event_sequence,
                    reason="supplied Harness state does not match durable Graph history",
                )
            if (
                approved
                and step.side_effect_handler is not None
                and (not isinstance(approval_ref, str) or not approval_ref.strip())
            ):
                raise HarnessValidationError(
                    "effectful approval resume requires an opaque durable approval ref",
                    code="side_effect_approval_ref_required",
                    details={
                        "code": "side_effect_approval_ref_required",
                        "step_id": node.step_id,
                    },
                )
        resolved_reason = reason or (
            "Harness approval granted" if approved else "Harness approval was cancelled"
        )
        resolved_approval_ref = (
            approval_ref.strip()
            if isinstance(approval_ref, str) and approval_ref.strip()
            else checksum_for(
                {
                    "policy": "approval_recorded",
                    "run_id": run_spec.run_id,
                    "node_instance_id": node.instance_id,
                    "attempt": node.attempt,
                    "approved": approved,
                    "reason": resolved_reason,
                }
            )
        )
        actor_scope_ref = checksum_for(
            {
                "source": "harness.resume_after_approval",
                "run_id": run_spec.run_id,
                "node_instance_id": node.instance_id,
            }
        )
        cause = HarnessWaitApprovalEvidenceRecord(
            scope=HarnessWaitScope(
                wait_id=registration.wait_id,
                run_id=run_spec.run_id,
                node_instance_id=node.instance_id,
                tenant_scope_ref=registration.tenant_scope_ref,
                identity_scope_ref=registration.identity_scope_ref,
                signal_schema_ref=registration.signal_schema_ref,
                correlation_ref=registration.correlation_ref,
            ),
            approval_event_ref=resolved_approval_ref,
            actor_identity_scope_ref=actor_scope_ref,
            approved=approved,
            recorded_sequence=0,
        )
        resumed = self.accept_graph_wait_cause(
            run_spec,
            cause,
            occurred_at=_graph_time(
                run_spec, self._next_graph_sequence(run_spec.run_id)
            ),
        )
        return self._drive_graph(run_spec, resumed)

    def _prepare_worker_side_effect(
        self,
        state: HarnessState,
        *,
        decided_at: Any,
        decision_input: Mapping[str, Any],
        step_id: str,
        worker_result: HarnessWorkerResult | None,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
    ) -> _PreparedSideEffect | None:
        declared_binding = self._side_effect_bindings_by_run.get(
            state.run_spec.run_id,
            {},
        ).get(step_id)
        intent = None if worker_result is None else worker_result.effect_intent
        if declared_binding is None:
            if intent is not None:
                raise HarnessValidationError(
                    "worker returned a side-effect intent for an undeclared step",
                    code="undeclared_side_effect_intent",
                    details={
                        "code": "undeclared_side_effect_intent",
                        "step_id": step_id,
                    },
                )
            return None
        if worker_result is None or intent is None:
            raise HarnessValidationError(
                "declared side-effect step requires one typed worker intent",
                code="side_effect_intent_missing",
                details={"code": "side_effect_intent_missing", "step_id": step_id},
            )
        if not gate_results or any(not result.passed for result in gate_results):
            raise HarnessValidationError(
                "side-effect authorization requires passing deterministic gate evidence",
                code="side_effect_gate_evidence_missing",
                details={
                    "code": "side_effect_gate_evidence_missing",
                    "step_id": step_id,
                },
            )
        if quality_verdict is not None and not quality_verdict.passed:
            raise HarnessValidationError(
                "side-effect authorization requires a passing aggregate verdict",
                code="side_effect_verdict_failed",
                details={"code": "side_effect_verdict_failed", "step_id": step_id},
            )
        bound_intent = self._bind_worker_side_effect_intent(
            state,
            step_id=step_id,
            worker_result=worker_result,
            intent=intent,
            binding=declared_binding,
        )
        authorization = self._build_worker_side_effect_decision(
            state,
            step_id=step_id,
            intent=bound_intent,
            binding=declared_binding,
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            decision_input=decision_input,
            decided_at=decided_at,
        )
        return _PreparedSideEffect(
            slot=step_id,
            intent=bound_intent,
            authorization=authorization,
            binding=declared_binding,
            prepare=True,
        )

    def _bind_worker_side_effect_intent(
        self,
        state: HarnessState,
        *,
        step_id: str,
        worker_result: HarnessWorkerResult,
        intent: HarnessSideEffectIntent,
        binding: HarnessSideEffectHandlerBinding,
    ) -> HarnessSideEffectIntent:
        step_state = get_step_state(state, step_id)
        if (
            intent.origin is not HarnessSideEffectOrigin.WORKER
            or intent.run_id != state.run_spec.run_id
            or intent.step_id != step_id
            or intent.attempt != step_state.attempts
        ):
            raise HarnessValidationError(
                "worker side-effect intent does not match run, step, and attempt identity",
                code="side_effect_intent_identity_mismatch",
                details={
                    "code": "side_effect_intent_identity_mismatch",
                    "step_id": step_id,
                },
            )
        expected_identity_scope = _expected_identity_scope_ref(state, step_id)
        expected_subject_scope = _expected_subject_scope_ref(state)
        if (
            expected_identity_scope is not None
            and intent.identity_scope_ref != expected_identity_scope
        ):
            raise HarnessValidationError(
                "worker side-effect intent identity scope mismatch",
                code="side_effect_scope_mismatch",
                details={"code": "side_effect_scope_mismatch", "scope": "identity"},
            )
        if (
            expected_subject_scope is not None
            and intent.subject_scope_ref != expected_subject_scope
        ):
            raise HarnessValidationError(
                "worker side-effect intent subject scope mismatch",
                code="side_effect_scope_mismatch",
                details={"code": "side_effect_scope_mismatch", "scope": "subject"},
            )
        if intent.kind != binding.kind:
            raise HarnessValidationError(
                "worker side-effect intent kind conflicts with workflow declaration",
                code="side_effect_handler_kind_mismatch",
            )
        if intent.handler != binding.reference:
            raise HarnessValidationError(
                "worker side-effect intent handler conflicts with workflow declaration",
                code="side_effect_handler_mismatch",
            )
        worker_result_ref = worker_result.candidate_result_ref
        candidate_checksum = checksum_for(
            {
                "worker_result_ref": worker_result_ref,
                "payload": intent.payload,
                "candidate_refs": intent.candidate_refs,
                "atomic_group": intent.atomic_group,
            }
        )
        return replace(
            intent,
            worker_result_ref=worker_result_ref,
            source_intent_ref=intent.checksum,
            candidate_checksum=candidate_checksum,
            checksum=None,
        )

    def _build_worker_side_effect_decision(
        self,
        state: HarnessState,
        *,
        step_id: str,
        intent: HarnessSideEffectIntent,
        binding: HarnessSideEffectHandlerBinding,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        decision_input: Mapping[str, Any],
        decided_at: Any,
    ) -> HarnessSideEffectDecision:
        step_spec = _get_step_spec(state, step_id)
        step_state = get_step_state(state, step_id)
        approval_ref = self._resolve_worker_side_effect_approval(
            state,
            step_id=step_id,
            intent=intent,
        )
        budget = self._budget_snapshot(state, None)
        gate_refs, gate_result_refs = _side_effect_gate_refs(gate_results)
        allowed_attempts = min(
            step_spec.retry_policy.effective_max_attempts,
            state.run_spec.budget.max_retries_per_step + 1,
        )
        decision_identity = {
            "intent_ref": intent.checksum,
            "handler": str(binding.reference),
            "gate_result_refs": gate_result_refs,
            "approval_evidence_ref": approval_ref,
            "budget_ref": checksum_for(budget.to_dict()),
            "command_ordinal": int(decision_input["command_ordinal"]),
            "causation_id": str(decision_input["causation_id"]),
        }
        return HarnessSideEffectDecision(
            decision_id=f"harness-side-effect-decision:{checksum_for(decision_identity).removeprefix('sha256:')}",
            intent_ref=intent.checksum,
            effect_id=intent.effect_id,
            kind=intent.kind,
            origin=intent.origin,
            run_id=intent.run_id,
            handler=binding.reference,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            idempotency_key=intent.idempotency_key,
            command_ordinal=int(decision_input["command_ordinal"]),
            causation_id=str(decision_input["causation_id"]),
            disposition=HarnessSideEffectDisposition.PREPARED,
            step_id=step_id,
            attempt=step_state.attempts,
            worker_result_ref=intent.worker_result_ref,
            gate_refs=gate_refs,
            gate_result_refs=gate_result_refs,
            aggregate_verdict_ref=_side_effect_aggregate_verdict_ref(
                gate_results,
                gate_result_refs=gate_result_refs,
                quality_verdict=quality_verdict,
            ),
            approval_evidence_ref=approval_ref,
            budget_ref=checksum_for(budget.to_dict()),
            effect_attempt=1,
            effect_attempt_limit=allowed_attempts,
            decided_at=decided_at,
        )

    def _resolve_worker_side_effect_approval(
        self,
        state: HarnessState,
        *,
        step_id: str,
        intent: HarnessSideEffectIntent,
    ) -> str:
        step_spec = _get_step_spec(state, step_id)
        if step_spec.metadata.get("approval_required") is not True:
            return checksum_for(
                {
                    "policy": "not_required",
                    "step_id": step_id,
                    "handler": str(step_spec.side_effect_handler),
                    "version": "1",
                }
            )
        step_state = get_step_state(state, step_id)
        approval_ref = step_state.metadata.get("approval_evidence_ref")
        if not isinstance(approval_ref, str) or not approval_ref.strip():
            raise HarnessValidationError(
                "effectful step has no durable approval evidence ref",
                code="side_effect_approval_missing",
            )
        if self.approval_evidence_resolver is None:
            raise HarnessValidationError(
                "effectful step requires an injected approval evidence resolver",
                code="side_effect_approval_resolver_missing",
            )
        evidence = self.approval_evidence_resolver.resolve(
            HarnessSideEffectApprovalRequest(
                run_id=state.run_spec.run_id,
                step_id=step_id,
                attempt=step_state.attempts,
                effect_id=intent.effect_id,
                candidate_checksum=intent.candidate_checksum,
                identity_scope_ref=intent.identity_scope_ref,
                subject_scope_ref=intent.subject_scope_ref,
                decision_version="1",
            ),
            approval_ref=approval_ref,
        )
        return evidence.approval_ref

    def _execute_prepared_side_effect(
        self,
        prepared: _PreparedSideEffect,
    ) -> HarnessSideEffectOutcome:
        outcome = self._commit_authorized_side_effect(
            prepared.intent,
            prepared.authorization,
            binding=prepared.binding,
            prepare=prepared.prepare,
        )
        run_id = prepared.intent.run_id
        self._side_effect_intents.setdefault(run_id, {})[prepared.slot] = (
            prepared.intent
        )
        self._side_effect_outcomes.setdefault(run_id, {})[prepared.slot] = outcome
        return outcome

    def _commit_authorized_side_effect(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        *,
        binding: HarnessSideEffectHandlerBinding,
        prepare: bool,
    ) -> HarnessSideEffectOutcome:
        if self.side_effect_store is None:  # pragma: no cover - preflight enforces this
            raise HarnessValidationError("side-effect store is unavailable")
        committed_decision = self.side_effect_store.put_decision(authorization)
        if committed_decision != authorization:
            raise HarnessValidationError(
                "side-effect store returned a conflicting authorization"
            )
        existing = self.side_effect_store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if existing is None:
            if binding.capabilities.physical_concurrency_safe:
                self._execute_fenced_side_effect(
                    intent,
                    authorization,
                    binding=binding,
                )
            else:
                self.side_effect_store.reserve_attempt(authorization)
                handler_method = (
                    getattr(binding.handler, "prepare", None) if prepare else None
                )
                if not callable(handler_method):
                    handler_method = binding.handler.commit
                outcome = handler_method(intent, authorization)
                if not isinstance(outcome, HarnessSideEffectOutcome):
                    raise HarnessValidationError(
                        "side-effect handler returned an invalid outcome"
                    )
                self.side_effect_store.put_outcome(outcome)
        resolved = self.side_effect_store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if resolved is None:
            raise HarnessValidationError(
                "side-effect outcome is not durably readable",
                code="side_effect_outcome_missing",
            )
        _validate_side_effect_outcome(intent, authorization, resolved)
        return resolved

    def _execute_fenced_side_effect(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        *,
        binding: HarnessSideEffectHandlerBinding,
    ) -> HarnessSideEffectOutcome:
        store = self.side_effect_store
        handler = binding.handler
        if not isinstance(store, HarnessFencedSideEffectStorePort):
            raise HarnessValidationError(
                "parallel-safe side effect requires a fenced durable store",
                code="fenced_side_effect_store_missing",
            )
        if not isinstance(handler, HarnessFencedSideEffectHandler):
            raise HarnessValidationError(
                "parallel-safe side effect requires a fenced handler",
                code="fenced_side_effect_handler_missing",
            )

        attempt = self._acquire_fenced_side_effect_attempt(
            store,
            handler,
            intent,
            authorization,
        )
        if isinstance(attempt, HarnessSideEffectOutcome):
            return attempt
        try:
            outcome = handler.commit_fenced(intent, authorization, attempt)
            if not isinstance(outcome, HarnessSideEffectOutcome):
                raise HarnessValidationError(
                    "fenced side-effect handler returned an invalid outcome",
                    code="invalid_fenced_side_effect_outcome",
                )
        except Exception as exc:
            reconciled = self._reconcile_fenced_side_effect_attempt(
                store,
                handler,
                intent,
                authorization,
                attempt,
                cause=exc,
            )
            if reconciled is not None:
                return reconciled
            raise
        return self._complete_fenced_side_effect_attempt(
            store,
            handler,
            intent,
            authorization,
            attempt,
            outcome,
        )

    def _acquire_fenced_side_effect_attempt(
        self,
        store: HarnessFencedSideEffectStorePort,
        handler: HarnessFencedSideEffectHandler,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectAttemptLease | HarnessSideEffectOutcome:
        try:
            return store.acquire_attempt(
                authorization,
                owner_id=self._side_effect_attempt_owner_id,
                lease_id=f"harness-side-effect-lease:{uuid4().hex}",
            )
        except HarnessValidationError as exc:
            if exc.code != "side_effect_attempt_termination_unconfirmed":
                raise
            current = store.get_attempt(
                effect_id=intent.effect_id,
                identity_scope_ref=intent.identity_scope_ref,
                subject_scope_ref=intent.subject_scope_ref,
            )
            if current is None:
                raise EventStoreCorruptionError(
                    "fenced side-effect attempt evidence disappeared during recovery"
                ) from exc
            reconciled = self._reconcile_fenced_side_effect_attempt(
                store,
                handler,
                intent,
                authorization,
                current,
                cause=exc,
            )
            if reconciled is not None:
                return reconciled
            return store.acquire_attempt(
                authorization,
                owner_id=self._side_effect_attempt_owner_id,
                lease_id=f"harness-side-effect-lease:{uuid4().hex}",
            )

    def _reconcile_fenced_side_effect_attempt(
        self,
        store: HarnessFencedSideEffectStorePort,
        handler: HarnessFencedSideEffectHandler,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt: HarnessSideEffectAttemptLease,
        *,
        cause: Exception,
    ) -> HarnessSideEffectOutcome | None:
        committed = self._read_fenced_side_effect_outcome(
            store,
            intent,
            authorization,
        )
        if committed is not None:
            return committed

        try:
            handler.request_cancellation(attempt)
        except Exception:
            pass

        reconciled = None
        try:
            reconciled = handler.reconcile(intent, authorization, attempt)
        except Exception:
            reconciled = None
        if reconciled is not None:
            if not isinstance(reconciled, HarnessSideEffectOutcome):
                raise HarnessValidationError(
                    "side-effect reconciliation returned an invalid outcome",
                    code="invalid_fenced_side_effect_outcome",
                ) from cause
            return self._commit_reconciled_side_effect_attempt(
                store,
                intent,
                authorization,
                attempt,
                reconciled,
            )

        try:
            termination_confirmed = handler.confirm_termination(attempt)
        except Exception:
            termination_confirmed = False
        if not isinstance(termination_confirmed, bool):
            termination_confirmed = False
        try:
            store.finish_attempt(
                attempt,
                termination_confirmed=termination_confirmed,
            )
        except HarnessValidationError as exc:
            if exc.code != "stale_side_effect_attempt":
                raise
            committed = self._read_fenced_side_effect_outcome(
                store,
                intent,
                authorization,
            )
            if committed is None:
                raise
            return committed
        if not termination_confirmed:
            raise HarnessValidationError(
                "side-effect attempt termination or external outcome is indeterminate",
                code="side_effect_attempt_indeterminate",
                details={
                    "code": "side_effect_attempt_indeterminate",
                    "effect_ref": checksum_for(intent.effect_id),
                    "attempt_id": attempt.attempt_id,
                    "fencing_generation": attempt.fencing_generation,
                },
            ) from cause
        return None

    def _complete_fenced_side_effect_attempt(
        self,
        store: HarnessFencedSideEffectStorePort,
        handler: HarnessFencedSideEffectHandler,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        try:
            committed = store.complete_attempt(attempt, outcome)
        except HarnessValidationError as exc:
            if exc.code == "side_effect_attempt_lease_expired":
                reconciled = self._reconcile_fenced_side_effect_attempt(
                    store,
                    handler,
                    intent,
                    authorization,
                    attempt,
                    cause=exc,
                )
                if reconciled is None:
                    raise
                return reconciled
            if exc.code != "stale_side_effect_attempt":
                raise
            committed = self._read_fenced_side_effect_outcome(
                store,
                intent,
                authorization,
            )
            if committed is None:
                raise
        _validate_side_effect_outcome(intent, authorization, committed)
        return committed

    def _commit_reconciled_side_effect_attempt(
        self,
        store: HarnessFencedSideEffectStorePort,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        try:
            committed = store.reconcile_attempt(attempt, outcome)
        except HarnessValidationError as exc:
            if exc.code != "stale_side_effect_attempt":
                raise
            committed = self._read_fenced_side_effect_outcome(
                store,
                intent,
                authorization,
            )
            if committed is None:
                raise
        _validate_side_effect_outcome(intent, authorization, committed)
        return committed

    @staticmethod
    def _read_fenced_side_effect_outcome(
        store: HarnessFencedSideEffectStorePort,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome | None:
        committed = store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if committed is not None:
            _validate_side_effect_outcome(intent, authorization, committed)
        return committed

    def _prepare_terminal_side_effect(
        self,
        state: HarnessState,
        *,
        decided_at: Any,
        decision_input: Mapping[str, Any],
    ) -> _PreparedSideEffect | None:
        policy = state.run_spec.workflow.terminal_side_effect_policy
        if policy is None:
            return None
        binding = self._terminal_side_effect_bindings.get(state.run_spec.run_id)
        if binding is None:
            raise HarnessValidationError(
                "terminal side-effect handler binding is unavailable",
                code="terminal_side_effect_policy_missing",
            )
        graph = self._prepared_graphs.get(state.run_spec.run_id)
        compensation_node_ids = (
            frozenset()
            if graph is None
            else frozenset(
                item.compensation_node_id for item in graph.compensation_refs
            )
        )
        forward_step_ids = (
            frozenset(step.step_id for step in state.step_states)
            if graph is None
            else frozenset(
                node.step_id
                for node in graph.nodes
                if isinstance(node, HarnessExecutableNode)
                and node.node_id not in compensation_node_ids
            )
        )
        if any(
            step.step_id in forward_step_ids
            and step.status is not HarnessStepStatus.SUCCEEDED
            for step in state.step_states
        ):
            raise HarnessValidationError(
                "terminal side effect requires every step outcome to be durable and successful",
                code="terminal_side_effect_steps_incomplete",
            )
        run_id = state.run_spec.run_id
        state_checksum = decision_input.get("graph_projection_checksum")
        if not _is_checksum_ref(state_checksum):
            raise HarnessValidationError(
                "terminal side effect requires its durable Graph preparation checksum",
                code="graph_side_effect_preparation_mismatch",
            )
        completion_input_ref = checksum_for(decision_input)
        identity_scope_ref = _expected_identity_scope_ref(state, state.current_step_id)
        subject_scope_ref = _expected_subject_scope_ref(state)
        if identity_scope_ref is None or subject_scope_ref is None:
            raise HarnessValidationError(
                "terminal side effect has no authoritative scope refs",
                code="side_effect_scope_missing",
            )
        prepared = self._durable_prepared_outcomes(state)
        atomic_groups = {outcome.atomic_group for outcome in prepared}
        if len(atomic_groups) > 1:
            raise HarnessValidationError(
                "terminal publication cannot combine conflicting atomic groups",
                code="side_effect_atomic_group_mismatch",
            )
        candidate_refs = tuple(
            ref for outcome in prepared for ref in outcome.candidate_refs
        )
        effect_identity = {
            "run_id": run_id,
            "policy": policy.reference,
            "state_checksum": state_checksum,
            "completion_input_ref": completion_input_ref,
        }
        terminal_payload: dict[str, Any] = {
            "prepared_outcome_refs": [outcome.checksum for outcome in prepared],
            "history_cutoff": self._terminal_history_cutoff(run_id),
        }
        tenant_id = state.run_spec.metadata.get("graph_terminal_tenant_id")
        if graph is not None and isinstance(tenant_id, str) and tenant_id.strip():
            terminal_payload["graph_terminal_manifest_context"] = {
                "tenant_id": tenant_id,
                "graph_id": graph.graph_id,
                "graph_version": graph.identity_version,
                "graph_schema_version": graph.schema_version,
                "compiler_version": graph.compiler_version,
                "normalized_graph_checksum": graph.checksum,
                "started_at": format_datetime(state.run_spec.created_at),
                "terminal_node_ids": list(graph.terminal_node_ids),
            }
        intent = HarnessSideEffectIntent(
            effect_id=f"harness-terminal-effect:{checksum_for(effect_identity).removeprefix('sha256:')}",
            kind=policy.kind,
            run_id=run_id,
            origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL,
            atomic_group=(
                prepared[0].atomic_group
                if prepared
                else f"terminal:{checksum_for({'run_id': run_id}).removeprefix('sha256:')}"
            ),
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
            terminal_action="complete_run",
            state_checksum=state_checksum,
            completion_input_ref=completion_input_ref,
            handler=policy.handler,
            payload=terminal_payload,
            candidate_refs=candidate_refs,
        )
        approval_ref = policy.not_required_evidence_ref
        if policy.requires_approval:
            configured_ref = state.run_spec.metadata.get(
                "terminal_approval_evidence_ref"
            )
            if not isinstance(configured_ref, str) or not configured_ref.strip():
                raise HarnessValidationError(
                    "terminal side effect requires durable approval evidence",
                    code="side_effect_approval_missing",
                )
            if self.approval_evidence_resolver is None:
                raise HarnessValidationError(
                    "terminal side effect requires an approval evidence resolver",
                    code="side_effect_approval_resolver_missing",
                )
            evidence = self.approval_evidence_resolver.resolve(
                HarnessSideEffectApprovalRequest(
                    run_id=run_id,
                    step_id="__terminal__",
                    attempt=1,
                    effect_id=intent.effect_id,
                    candidate_checksum=completion_input_ref,
                    identity_scope_ref=identity_scope_ref,
                    subject_scope_ref=subject_scope_ref,
                    decision_version=policy.version,
                ),
                approval_ref=configured_ref,
            )
            approval_ref = evidence.approval_ref
        assert approval_ref is not None
        gate_refs, gate_result_refs, aggregate_verdict_ref = (
            _side_effect_gate_refs_from_history(
                self._committed_events,
                run_id=run_id,
            )
        )
        if policy.inherited_gate_refs:
            required = set(policy.inherited_gate_refs)
            if not required.issubset(set(gate_refs)):
                raise HarnessValidationError(
                    "terminal side-effect policy gate evidence is incomplete",
                    code="terminal_side_effect_gate_evidence_missing",
                    details={
                        "code": "terminal_side_effect_gate_evidence_missing",
                        "missing": sorted(required.difference(gate_refs)),
                    },
                )
        budget_ref = checksum_for(self._budget_snapshot(state, None).to_dict())
        authorization = HarnessSideEffectDecision(
            decision_id=f"harness-side-effect-decision:{checksum_for({'intent_ref': intent.checksum, 'policy': policy.reference, 'budget_ref': budget_ref}).removeprefix('sha256:')}",
            intent_ref=intent.checksum,
            effect_id=intent.effect_id,
            kind=intent.kind,
            origin=intent.origin,
            run_id=run_id,
            handler=binding.reference,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            idempotency_key=intent.idempotency_key,
            command_ordinal=int(decision_input["command_ordinal"]),
            causation_id=str(decision_input["causation_id"]),
            disposition=HarnessSideEffectDisposition.ACCEPTED,
            terminal_action="complete_run",
            terminal_state_ref=state_checksum,
            gate_refs=gate_refs,
            gate_result_refs=gate_result_refs,
            aggregate_verdict_ref=aggregate_verdict_ref,
            approval_evidence_ref=approval_ref,
            budget_ref=budget_ref,
            effect_attempt=1,
            effect_attempt_limit=policy.retry_limit,
            decision_version=policy.version,
            decided_at=decided_at,
        )
        return _PreparedSideEffect(
            slot="__terminal__",
            intent=intent,
            authorization=authorization,
            binding=binding,
            prepare=False,
        )

    def _terminal_history_cutoff(self, run_id: str) -> str | None:
        return (
            None if not self._committed_events else self._committed_events[-1].event_id
        )

    def _durable_prepared_outcomes(
        self,
        state: HarnessState,
    ) -> tuple[HarnessSideEffectOutcome, ...]:
        if self.side_effect_store is None:
            return ()
        outcomes: list[tuple[int, HarnessSideEffectOutcome]] = []
        for decision in self.side_effect_store.list_decisions(
            run_id=state.run_spec.run_id
        ):
            if decision.origin is not HarnessSideEffectOrigin.WORKER:
                continue
            outcome = self.side_effect_store.get_outcome(
                effect_id=decision.effect_id,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
                idempotency_key=decision.idempotency_key,
            )
            if outcome is None:
                continue
            if outcome.disposition is HarnessSideEffectDisposition.PREPARED:
                outcomes.append((decision.command_ordinal, outcome))
        return tuple(
            outcome
            for _, outcome in sorted(
                outcomes,
                key=lambda item: (item[0], item[1].outcome_id),
            )
        )

    def _quarantine_prepared_side_effects(self, state: HarnessState) -> None:
        if self.side_effect_store is None:
            return
        run_id = state.run_spec.run_id
        for decision in self.side_effect_store.list_decisions(run_id=run_id):
            outcome = self.side_effect_store.get_outcome(
                effect_id=decision.effect_id,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
                idempotency_key=decision.idempotency_key,
            )
            if (
                outcome is None
                or outcome.disposition is not HarnessSideEffectDisposition.PREPARED
            ):
                continue
            quarantined = self.side_effect_store.set_disposition(
                effect_id=decision.effect_id,
                disposition=HarnessSideEffectDisposition.QUARANTINE,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
            )
            if quarantined is not None:
                slot = decision.step_id or "__terminal__"
                self._side_effect_outcomes.setdefault(run_id, {})[slot] = quarantined

    def _evaluate_gate(
        self,
        gate: DeterministicGate,
        *,
        reference: str,
        context: GateContext,
    ) -> HarnessGateResult:
        expected_gate_name = GateReference.parse(reference).gate_id
        input_ref = _gate_input_ref(context, reference)
        try:
            result = gate.evaluate(context)
        except Exception as exc:
            result = HarnessGateResult(
                gate_name=expected_gate_name,
                passed=False,
                reason="deterministic gate evaluation failed",
                details={
                    "reason_code": "gate_exception",
                    "exception_type": type(exc).__name__,
                },
            )
        if not isinstance(result, HarnessGateResult):
            result = HarnessGateResult(
                gate_name=expected_gate_name,
                passed=False,
                reason="deterministic gate returned an invalid result",
                details={"reason_code": "invalid_gate_result"},
            )
        elif result.gate_name != expected_gate_name:
            result = HarnessGateResult(
                gate_name=expected_gate_name,
                passed=False,
                reason="deterministic gate result identity mismatch",
                details={
                    "reason_code": "gate_identity_mismatch",
                    "actual_gate_name": result.gate_name,
                },
            )
        elif not _is_valid_gate_result(result):
            result = HarnessGateResult(
                gate_name=expected_gate_name,
                passed=False,
                reason="deterministic gate returned an invalid result",
                details={"reason_code": "invalid_gate_result"},
            )
        reason_code = result.details.get("reason_code")
        if not isinstance(reason_code, str) or not reason_code.strip():
            reason_code = "gate_passed" if result.passed else "gate_failed"
        return result.with_evidence(
            gate_reference=reference,
            input_ref=input_ref,
            reason_code=reason_code,
        )

    def _budget_snapshot(
        self,
        state: HarnessState,
        worker_result: HarnessWorkerResult | None,
    ) -> HarnessBudgetSnapshot:
        return HarnessBudgetSnapshot.from_budget(
            state.run_spec.budget,
            turns_used=state.turn_count,
            replans_used=state.replan_count,
            worker_calls_used=state.worker_call_count,
            evolution_epochs_used=int(state.metadata.get("evolution_epochs_used", 0)),
            candidates_used=int(state.metadata.get("candidates_used", 0)),
            patch_operations_used=int(state.metadata.get("patch_operations_used", 0)),
            eval_cases_used=int(state.metadata.get("eval_cases_used", 0)),
            sandbox_runs_used=int(state.metadata.get("sandbox_runs_used", 0)),
        )


    def _record_event(self, event: HarnessEvent) -> HarnessEvent:
        committed = self.event_port.record(event)
        if not isinstance(committed, HarnessEvent):
            raise HarnessValidationError(
                "Harness event_port must return the authoritative committed HarnessEvent projection"
            )
        if (
            committed.run_id != event.run_id
            or committed.step_id != event.step_id
            or committed.event_type != event.event_type
        ):
            raise HarnessValidationError(
                "Harness event_port returned a conflicting committed projection"
            )
        self._committed_events.append(committed)
        return committed

def _event_activity_from_graph(
    activity: HarnessGraphActivity,
    step: HarnessStepSpec,
) -> HarnessActivity:
    return HarnessActivity(
        activity_id=activity.activity_id,
        run_id=activity.run_id,
        step_id=step.step_id,
        attempt=activity.attempt,
        activity_type=step.worker_type.value,
        idempotency_key=activity.idempotency_key,
        input_checksum=activity.input_ref,
        identity_scope_ref=activity.identity_scope_ref,
        contract_version=HARNESS_ACTIVITY_CONTRACT,
        worker_version=activity.worker_ref.version,
    )


def _graph_compat_terminal_reason(
    reason_code: str | None,
    *,
    outcome: RunOutcome,
) -> str | None:
    if reason_code is None:
        return "workflow has no next step" if outcome is RunOutcome.SUCCEEDED else None
    return {
        "verification_failed_replans_exhausted": (
            "verification failed and replan budget is exhausted"
        ),
        "plan_failed_replans_exhausted": (
            "plan gate failed and replan budget is exhausted"
        ),
        "side_effect_retry_exhausted": ("side-effect failure: effect_retry_exhausted"),
    }.get(reason_code, reason_code)


def _graph_time(run_spec: HarnessRunSpec, sequence: int):
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise HarnessValidationError("graph sequence must be a non-negative integer")
    return run_spec.created_at + timedelta(microseconds=sequence)


def _graph_node_by_instance(
    state: HarnessGraphState,
    node_instance_id: str,
) -> HarnessNodeInstanceState:
    node = next(
        (item for item in state.node_instances if item.instance_id == node_instance_id),
        None,
    )
    if node is None:
        raise EventIncompleteHistoryError(
            "graph node instance is absent from the current projection"
        )
    return node


def _graph_side_effect_outcome_for_completion(
    state: HarnessGraphState,
    decision: HarnessGraphDecision,
) -> str | None:
    if decision.decision_type not in {
        HarnessGraphDecisionType.COMPLETE_NODE,
        HarnessGraphDecisionType.COMPLETE_RUN,
    }:
        return None
    outcome_ref = decision.payload.get("side_effect_outcome_ref")
    if outcome_ref is None:
        return None
    if not _is_checksum_ref(outcome_ref):
        raise HarnessValidationError(
            "Graph completion contains an invalid side-effect outcome reference",
            code="graph_decision_side_effect_outcome_mismatch",
        )
    raw_pending: Any
    if decision.decision_type is HarnessGraphDecisionType.COMPLETE_NODE:
        if decision.node_instance_id is None:
            raise HarnessValidationError(
                "effectful node completion requires exact node identity",
                code="graph_step_decision_identity_missing",
            )
        raw_pending = _graph_node_by_instance(
            state,
            decision.node_instance_id,
        ).metadata.get("pending_side_effect")
    else:
        raw_pending = state.metadata.get("pending_terminal_side_effect")
    if not isinstance(raw_pending, Mapping):
        raise HarnessValidationError(
            "Graph completion has no durable side-effect preparation",
            code="graph_side_effect_preparation_missing",
        )
    pending = HarnessPendingSideEffectState.from_dict(raw_pending)
    if (
        pending.status is not HarnessPendingSideEffectStatus.OUTCOME_RECORDED
        or pending.outcome_ref != outcome_ref
        or pending.prepare_decision_ref
        != decision.payload.get("side_effect_prepare_decision_ref")
        or outcome_ref not in decision.evidence_refs
    ):
        raise HarnessValidationError(
            "Graph completion conflicts with its accepted side-effect outcome",
            code="graph_side_effect_preparation_mismatch",
        )
    return outcome_ref


def _graph_node_for_step(
    state: HarnessGraphState,
    step_id: str,
) -> HarnessNodeInstanceState:
    matches = tuple(item for item in state.node_instances if item.step_id == step_id)
    if not matches:
        raise EventIncompleteHistoryError("graph Step has no activated node instance")
    return max(
        matches,
        key=lambda item: (
            item.identity.activation_ordinal,
            item.last_event_sequence,
            item.instance_id,
        ),
    )


def _graph_evidence_for_observation(
    node: HarnessNodeInstanceState,
    observation: HarnessAcceptedGraphObservation,
) -> HarnessAttemptEvidenceReference:
    evidence = next(
        (
            item
            for item in node.evidence_refs
            if item.evidence_ref == observation.evidence_ref
            and item.event_sequence == observation.event_sequence
            and item.contract_ref == observation.contract_ref
            and item.payload_ref == observation.payload_ref
        ),
        None,
    )
    if evidence is None:
        raise EventIncompleteHistoryError(
            "graph observation is missing its accepted node evidence"
        )
    return evidence


def _graph_gate_result_from_observation(
    observation: HarnessAcceptedGraphObservation,
) -> HarnessGateResult:
    if observation.observation_type is not HarnessGraphObservationType.GATE_RESULT:
        raise TypeError("observation must be a Graph gate result")
    return HarnessGateResult(
        gate_name=observation.contract_ref.contract_id,
        passed=bool(observation.payload["passed"]),
        details={
            "harness_gate": {
                "reference": observation.contract_ref.exact_ref,
                "input_ref": observation.payload["input_ref"],
                "result_ref": observation.payload["result_ref"],
                "reason_code": observation.payload["reason_code"],
            }
        },
    )


def _project_graph_control_facts(
    output: Mapping[str, Any],
    paths: tuple[str, ...],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for path in paths:
        source: Any = output
        segments = path.split(".")
        for segment in segments:
            if not isinstance(source, Mapping) or segment not in source:
                source = None
                break
            source = source[segment]
        target = projected
        for segment in segments[:-1]:
            child = target.get(segment)
            if not isinstance(child, dict):
                child = {}
                target[segment] = child
            target = child
        target[segments[-1]] = source
    return projected


def _side_effect_gate_refs(
    gate_results: tuple[HarnessGateResult, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    references: list[str] = []
    result_refs: list[str] = []
    for result in gate_results:
        evidence = gate_result_evidence(result)
        reference = evidence.get("reference")
        result_ref = evidence.get("result_ref")
        if not isinstance(reference, str) or not reference.strip():
            raise HarnessValidationError(
                "side-effect gate evidence is missing an exact reference"
            )
        if not _is_checksum_ref(result_ref):
            raise HarnessValidationError(
                "side-effect gate evidence is missing its result ref"
            )
        references.append(reference)
        result_refs.append(result_ref)
    return tuple(references), tuple(result_refs)


def _side_effect_aggregate_verdict_ref(
    gate_results: tuple[HarnessGateResult, ...],
    *,
    gate_result_refs: tuple[str, ...],
    quality_verdict: HarnessQualityVerdict | None,
) -> str:
    if quality_verdict is not None:
        return checksum_for(quality_verdict.to_dict())
    return checksum_for(
        {
            "gate_result_refs": list(gate_result_refs),
            "passed": bool(gate_results)
            and all(result.passed for result in gate_results),
        }
    )




def _side_effect_gate_refs_from_history(
    events: list[HarnessEvent],
    *,
    run_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    references: list[str] = []
    result_refs: list[str] = []
    aggregate: list[dict[str, Any]] = []
    for event in events:
        if (
            event.run_id != run_id
            or event.event_type is not HarnessEventType.GATE_EVALUATED
        ):
            continue
        payload = event.payload
        details = payload.get("details")
        harness_gate = (
            details.get("harness_gate") if isinstance(details, Mapping) else None
        )
        reference = (
            harness_gate.get("reference")
            if isinstance(harness_gate, Mapping)
            else payload.get("reference")
        )
        result_ref = (
            harness_gate.get("result_ref")
            if isinstance(harness_gate, Mapping)
            else payload.get("result_ref")
        )
        passed = payload.get("passed")
        if (
            isinstance(reference, str)
            and reference.strip()
            and _is_checksum_ref(result_ref)
        ):
            if not isinstance(passed, bool):
                raise HarnessValidationError(
                    "recorded terminal gate evidence has no verdict"
                )
            if reference not in references:
                references.append(reference)
            if result_ref not in result_refs:
                result_refs.append(result_ref)
            aggregate.append(
                {"reference": reference, "result_ref": result_ref, "passed": passed}
            )
    if not aggregate or any(not item["passed"] for item in aggregate):
        raise HarnessValidationError(
            "terminal side-effect authorization requires complete passing gate history",
            code="terminal_side_effect_gate_evidence_missing",
        )
    return (
        tuple(references),
        tuple(result_refs),
        checksum_for({"gate_evidence": aggregate}),
    )


def _expected_identity_scope_ref(
    state: HarnessState, step_id: str | None
) -> str | None:
    value = state.run_spec.metadata.get("identity_scope_ref")
    if _is_checksum_ref(value):
        if step_id is not None:
            activity_scope = get_step_state(state, step_id).metadata.get(
                "activity_identity_scope_ref"
            )
            if activity_scope is not None and activity_scope != value:
                raise HarnessValidationError(
                    "worker activity identity scope conflicts with run authority scope",
                    code="side_effect_scope_mismatch",
                )
        return value
    return None


def _expected_subject_scope_ref(state: HarnessState) -> str | None:
    value = state.run_spec.metadata.get("subject_scope_ref")
    if _is_checksum_ref(value):
        return value
    return None


def _validate_side_effect_outcome(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
    outcome: HarnessSideEffectOutcome,
) -> None:
    if (
        outcome.effect_id != intent.effect_id
        or outcome.decision_ref != authorization.checksum
        or outcome.run_id != intent.run_id
        or outcome.kind != intent.kind
        or outcome.handler != authorization.handler
        or outcome.idempotency_key != intent.idempotency_key
        or outcome.identity_scope_ref != intent.identity_scope_ref
        or outcome.subject_scope_ref != intent.subject_scope_ref
        or outcome.atomic_group != intent.atomic_group
        or outcome.disposition is not authorization.disposition
        or outcome.checksum is None
    ):
        raise HarnessValidationError(
            "durable side-effect outcome conflicts with authorization",
            code="side_effect_outcome_mismatch",
        )




def _gate_reference(gate: DeterministicGate) -> str:
    gate_name = str(getattr(gate, "gate_name", "")).strip()
    gate_version = str(getattr(gate, "gate_version", "1")).strip()
    try:
        return str(GateReference(gate_id=gate_name, version=gate_version))
    except HarnessValidationError as exc:
        raise HarnessValidationError(
            "deterministic gate requires an exact stable name and version",
            code=exc.code,
            details=exc.details,
        ) from exc


def _gate_input_ref(context: GateContext, reference: str) -> str:
    step_state = context.step_state.to_dict()
    step_metadata = dict(step_state.get("metadata", {}))
    # The worker result is already an explicit checksum input. In-memory state
    # retains a raw duplicate here while durable projections retain only refs.
    step_metadata.pop("worker_result", None)
    step_state["metadata"] = step_metadata
    return checksum_for(
        {
            "gate_reference": reference,
            "run_id": context.state.run_spec.run_id,
            "workflow": context.state.run_spec.workflow.to_dict(),
            "step_spec": context.step_spec.to_dict(),
            "step_state": step_state,
            "worker_result": (
                None
                if context.worker_result is None
                else context.worker_result.to_dict()
            ),
            "quality_verdict": (
                None
                if context.quality_verdict is None
                else context.quality_verdict.to_dict()
            ),
            "budget": None if context.budget is None else context.budget.to_dict(),
            "cumulative_budget_fact": (
                None
                if context.cumulative_budget_fact is None
                else context.cumulative_budget_fact.control_projection()
            ),
        }
    )


def _budget_fact_payload_matches(
    stored: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    projection = dict(stored)
    projection.pop("projection_schema", None)
    return projection == dict(expected)


def _is_valid_gate_result(result: HarnessGateResult) -> bool:
    if result.reason is not None and not isinstance(result.reason, str):
        return False
    score = result.details.get("score")
    if score is not None and (
        not isinstance(score, int | float)
        or isinstance(score, bool)
        or (isinstance(score, float) and not math.isfinite(score))
        or not 0 <= score <= 1
    ):
        return False
    if "repair_hints" in result.details:
        repair_hints = result.details["repair_hints"]
        if not isinstance(repair_hints, list | tuple) or any(
            not isinstance(hint, str) for hint in repair_hints
        ):
            return False
    if "reason_code" in result.details:
        reason_code = result.details["reason_code"]
        if not isinstance(reason_code, str) or not reason_code.strip():
            return False
    try:
        normalize_canonical_json(
            result.to_dict(),
            path="$.harness_gate_result",
        )
    except (TypeError, ValueError):
        return False
    return True


def _bind_step_value(
    bindings: dict[str, Any],
    step_id: str,
    value: Any,
    *,
    code: str,
) -> None:
    if step_id in bindings and bindings[step_id] != value:
        raise HarnessValidationError(
            "one workflow step resolves to conflicting graph runtime bindings",
            code=code,
            details={"code": code, "step_id": step_id},
        )
    bindings[step_id] = value


def _invoke_worker_delegate(
    adapter: _WorkerImplementationAdapter,
    task: dict[str, Any],
) -> HarnessWorkerResult:
    delegate = adapter.delegate
    if callable(delegate):
        return _coerce_worker_result(delegate(task))
    execute = getattr(delegate, "execute", None)
    if callable(execute):
        return _coerce_worker_result(execute(task))
    if adapter.worker_type is HarnessWorkerType.LLM:
        generate = getattr(delegate, "generate", None)
        if callable(generate):
            return _coerce_worker_result(generate(task))
    if adapter.worker_type is HarnessWorkerType.SKILL:
        run_skill = getattr(delegate, "run_skill", None)
        if callable(run_skill):
            return _coerce_worker_result(
                run_skill(
                    str(task.get("skill_name", task["step_id"])),
                    dict(task.get("inputs", {})),
                    dict(task.get("context", {})),
                )
            )
    if adapter.worker_type is HarnessWorkerType.SUBAGENT:
        run_subagent = getattr(delegate, "run_subagent", None)
        if callable(run_subagent):
            return _coerce_worker_result(
                run_subagent(
                    str(task.get("subagent_id", task["step_id"])),
                    dict(task),
                    dict(task.get("budget", {})),
                )
            )
    if adapter._queued_results is None:
        try:
            adapter._queued_results = list(delegate)
        except TypeError as exc:
            raise HarnessValidationError(
                "worker registry value must be callable, a Harness worker port, or result iterable",
                code="invalid_runtime_worker_implementation",
                details={"reference": f"{adapter.worker_id}@{adapter.worker_version}"},
            ) from exc
    if not adapter._queued_results:
        return HarnessWorkerResult(
            status=HarnessWorkerStatus.FAILED,
            error="fake worker queue is exhausted",
        )
    return _coerce_worker_result(adapter._queued_results.pop(0))


def _coerce_worker_result(value: Any) -> HarnessWorkerResult:
    to_dict = getattr(value, "to_dict", None)
    payload = to_dict() if callable(to_dict) else value
    try:
        return HarnessWorkerResult.from_dict(payload)
    except (TypeError, ValueError, HarnessValidationError) as exc:
        if isinstance(exc, HarnessValidationError):
            raise
        raise HarnessValidationError(
            "worker returned an invalid result contract"
        ) from exc


def _coerce_compensation_result(value: Any) -> HarnessWorkerResult:
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


def _is_checksum_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def _graph_declared_output_keys(graph: NormalizedHarnessGraph) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                key
                for definition in graph.nodes
                for key in _graph_node_output_keys(definition)
            }
        )
    )


def _graph_node_output_keys(definition: HarnessGraphNode) -> tuple[str, ...]:
    if isinstance(definition, HarnessExecutableNode):
        return definition.output_keys
    if isinstance(definition, HarnessControlNode) and definition.merge is not None:
        return definition.merge.output_keys
    return ()


def _graph_definition_by_id(
    graph: NormalizedHarnessGraph,
    node_id: str,
) -> HarnessGraphNode:
    definition = next(
        (item for item in graph.nodes if item.node_id == node_id),
        None,
    )
    if definition is None:
        raise EventIncompleteHistoryError(
            "graph output resolution cannot resolve a pinned node definition"
        )
    return definition


def _graph_path_distance(
    graph: NormalizedHarnessGraph,
    source_id: str,
    target_id: str,
) -> int | None:
    if source_id == target_id:
        return 0
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    frontier: list[tuple[str, int]] = [(source_id, 0)]
    visited = {source_id}
    while frontier:
        current, current_distance = frontier.pop(0)
        for target in sorted(adjacency.get(current, ())):
            if target == target_id:
                return current_distance + 1
            if target in visited:
                continue
            visited.add(target)
            frontier.append((target, current_distance + 1))
    return None


def _graph_scope_compatible(
    left: tuple[Any, ...],
    right: tuple[Any, ...],
) -> bool:
    common = min(len(left), len(right))
    return left[:common] == right[:common]


def _graph_candidate_dominates(
    candidate: tuple[HarnessNodeInstanceState, HarnessGraphNode, int | None],
    other: tuple[HarnessNodeInstanceState, HarnessGraphNode, int | None],
    *,
    distance: Callable[[str, str], int | None],
) -> bool:
    candidate_node, candidate_definition, _ = candidate
    other_node, other_definition, _ = other
    if candidate_definition.node_id == other_definition.node_id:
        return candidate_node.identity.activation_ordinal > (
            other_node.identity.activation_ordinal
        )
    forward = distance(other_definition.node_id, candidate_definition.node_id)
    if forward is None:
        return False
    reverse = distance(candidate_definition.node_id, other_definition.node_id)
    if reverse is None:
        return True
    return candidate_node.identity.activation_ordinal > (
        other_node.identity.activation_ordinal
    )


def _graph_executable_output_value(
    definition: HarnessExecutableNode,
    result: HarnessWorkerResult,
    output_key: str,
) -> Any:
    if result.status is not HarnessWorkerStatus.SUCCEEDED:
        raise EventIncompleteHistoryError(
            "successful graph output references a failed Worker result"
        )
    if output_key not in definition.output_keys:
        raise EventIncompleteHistoryError(
            "Worker output key is outside its pinned graph contract"
        )
    if len(definition.output_keys) == 1:
        return result.output
    if not isinstance(result.output, Mapping) or output_key not in result.output:
        raise EventIncompleteHistoryError(
            "multi-output Worker result is missing one pinned output key"
        )
    return result.output[output_key]




def _is_transition_port(value: Any) -> bool:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in (
            "record",
            "create_activity",
            "read_history",
            "require_activity_storage",
            "accept_activity",
            "resolve_graph_replay_activity",
            "record_activity_result",
        )
    )




def _get_step_spec(state: HarnessState, step_id: str) -> HarnessStepSpec:
    for step in state.run_spec.workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)
















def _task_with_activity(
    task: dict[str, Any],
    activity: HarnessActivity | None,
) -> dict[str, Any]:
    if activity is None:
        return dict(task)
    return {
        **task,
        "harness_activity": {
            "activity_id": activity.activity_id,
            "idempotency_key": activity.idempotency_key,
            "attempt": activity.attempt,
            "contract_version": activity.contract_version,
        },
    }


def _validate_merge_reference_manifest(
    value: Any,
    *,
    allowed_refs: set[str],
) -> None:
    if isinstance(value, str):
        if value not in allowed_refs:
            raise HarnessValidationError(
                "pure Merge output references data outside its exact inputs",
                code="graph_merge_output_reference_forged",
                details={"reference": value},
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise HarnessValidationError(
                    "pure Merge manifest keys must be non-empty strings",
                    code="graph_merge_output_contract_mismatch",
                )
            _validate_merge_reference_manifest(item, allowed_refs=allowed_refs)
        return
    if isinstance(value, tuple | list):
        for item in value:
            _validate_merge_reference_manifest(item, allowed_refs=allowed_refs)
        return
    raise HarnessValidationError(
        "pure Merge output may contain only exact input references",
        code="graph_merge_output_reference_forged",
    )




def _graph_worker_call_marker_committed(
    event_port: Any,
    *,
    run_id: str,
    activity_id: str,
) -> bool:
    return any(
        event.event_type is HarnessEventType.WORKER_CALLED
        and event.payload.get("activity_id") == activity_id
        for event in event_port.read_history(run_id)
    )




def _approval_resume_projection_checksum(state: HarnessState) -> str:
    """Compare durable approval state while ignoring lazily hydrated outputs."""

    projection = HarnessStateProjection.from_state(state).to_dict()
    metadata = dict(projection["metadata"])
    metadata.pop("outputs_count", None)
    metadata.pop("outputs_ref", None)
    projection["metadata"] = metadata
    return checksum_for(projection)


def _wait_cause_from_observation(
    observation: HarnessAcceptedGraphObservation,
) -> (
    HarnessWaitSignal
    | HarnessWaitTimerWakeRecord
    | HarnessWaitTimeoutRecord
    | HarnessWaitApprovalEvidenceRecord
    | HarnessWaitCancellationRecord
):
    payload = thaw_canonical_json(observation.payload)
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("record"),
        Mapping,
    ):
        raise EventStoreCorruptionError("Wait cause observation is malformed")
    kind = HarnessWaitCauseKind(payload.get("cause_kind"))
    record = payload["record"]
    if kind is HarnessWaitCauseKind.SIGNAL:
        return HarnessWaitSignal.from_dict(record)
    if kind is HarnessWaitCauseKind.TIMER:
        return HarnessWaitTimerWakeRecord.from_dict(record)
    if kind is HarnessWaitCauseKind.TIMEOUT:
        return HarnessWaitTimeoutRecord.from_dict(record)
    if kind is HarnessWaitCauseKind.APPROVAL:
        return HarnessWaitApprovalEvidenceRecord.from_dict(record)
    if kind is HarnessWaitCauseKind.CANCELLATION:
        return HarnessWaitCancellationRecord.from_dict(record)
    raise EventStoreCorruptionError("Wait cause observation kind is unsupported")


def _wait_cause_external_identity(
    cause: (
        HarnessWaitSignal
        | HarnessWaitTimerWakeRecord
        | HarnessWaitTimeoutRecord
        | HarnessWaitApprovalEvidenceRecord
        | HarnessWaitCancellationRecord
    ),
) -> tuple[str, str, str]:
    if isinstance(cause, HarnessWaitSignal):
        return (
            HarnessWaitCauseKind.SIGNAL.value,
            cause.scope.tenant_scope_ref,
            cause.signal_id,
        )
    if isinstance(cause, HarnessWaitTimerWakeRecord):
        value = cause.timer_event_ref
        kind = HarnessWaitCauseKind.TIMER
    elif isinstance(cause, HarnessWaitTimeoutRecord):
        value = cause.timeout_event_ref
        kind = HarnessWaitCauseKind.TIMEOUT
    elif isinstance(cause, HarnessWaitApprovalEvidenceRecord):
        value = cause.approval_event_ref
        kind = HarnessWaitCauseKind.APPROVAL
    else:
        value = cause.cancellation_event_ref
        kind = HarnessWaitCauseKind.CANCELLATION
    return kind.value, cause.scope.scope_ref, value


def _wait_cause_idempotency_projection(
    cause: (
        HarnessWaitSignal
        | HarnessWaitTimerWakeRecord
        | HarnessWaitTimeoutRecord
        | HarnessWaitApprovalEvidenceRecord
        | HarnessWaitCancellationRecord
    ),
) -> Mapping[str, Any]:
    if isinstance(cause, HarnessWaitSignal):
        return cause.idempotency_projection()
    projection = cause.to_dict()
    if isinstance(
        cause,
        HarnessWaitTimerWakeRecord | HarnessWaitApprovalEvidenceRecord,
    ):
        sequence_field = "recorded_sequence"
    elif isinstance(cause, HarnessWaitTimeoutRecord):
        sequence_field = "timed_out_sequence"
    else:
        sequence_field = "cancelled_sequence"
    projection.pop(sequence_field, None)
    return projection


def _wait_cause_identity_conflict_code(
    cause: (
        HarnessWaitSignal
        | HarnessWaitTimerWakeRecord
        | HarnessWaitTimeoutRecord
        | HarnessWaitApprovalEvidenceRecord
        | HarnessWaitCancellationRecord
    ),
) -> str:
    if isinstance(cause, HarnessWaitSignal):
        return "wait_signal_identity_conflict"
    return "graph_wait_cause_identity_conflict"


def _matching_graph_run_operation(
    recovery: HarnessGraphRecovery,
    requested: HarnessGraphRunOperation,
) -> HarnessGraphRunOperation | None:
    for commit in recovery.observation_commits:
        observation = commit.observation
        if observation.observation_type is not HarnessGraphObservationType.RUN_OPERATION:
            continue
        raw_record = observation.payload.get("record")
        if not isinstance(raw_record, Mapping):
            raise EventStoreCorruptionError(
                "Graph run operation observation is missing its typed record"
            )
        try:
            existing = HarnessGraphRunOperation.from_dict(raw_record)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise EventStoreCorruptionError(
                "Graph run operation observation violates its typed contract"
            ) from exc
        if existing.operation_identity_ref != requested.operation_identity_ref:
            continue
        if existing.idempotency_projection() != requested.idempotency_projection():
            raise HarnessValidationError(
                "Graph run operation identity was reused with conflicting content",
                code="graph_run_operation_identity_conflict",
            )
        return existing
    return None


def _restore_cache_value(
    cache: dict[str, Any],
    key: str,
    value: Any,
    missing: object,
) -> None:
    if value is missing:
        cache.pop(key, None)
    else:
        cache[key] = value


__all__ = ["HarnessControlPlane", "HarnessRunResult", "InMemoryHarnessEventPort"]
