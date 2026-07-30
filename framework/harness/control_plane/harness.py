from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable, Iterable

from framework.events.canonical import (
    PayloadReference,
    checksum_for,
    normalize_canonical_json,
)
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventReplayMismatchError,
    EventStoreCorruptionError,
)
from framework.events.runtime.activities import ReplayActivityDescriptor
from framework.events.runtime.history import DeterministicHistoryRecord
from framework.harness.control_plane.activity import (
    HARNESS_ACTIVITY_CONTRACT,
    HarnessActivity,
    validate_activity_call_marker,
)
from framework.harness.control_plane.decision import (
    HarnessDecision,
    HarnessDecisionType,
)
from framework.harness.control_plane.durable_events import (
    HarnessRecovery,
    HarnessTransitionCommit,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.event import HarnessEvent, HarnessEventType
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
    GateBinding,
    GateReference,
)
from framework.harness.control_plane.replay_history import (
    harness_decision_history,
    harness_decision_input_snapshot,
)
from framework.harness.control_plane.gates import (
    DeterministicGate,
    GateContext,
    HarnessGateResult,
    default_plan_gates,
    default_verify_gates,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphActivityDispatcherPort,
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.graph_decision import HarnessGraphDecision
from framework.harness.control_plane.graph_evaluator import (
    HarnessGraphEvaluationContext,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivityResult,
    HarnessGraphTransitionPort,
    InMemoryHarnessGraphTransitionPort,
)
from framework.harness.control_plane.graph_state import HarnessGraphState
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
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepStatus,
)
from framework.harness.control_plane.transitions import (
    get_step_state,
    replace_step_state,
    terminal_run_statuses,
    transition_run,
    transition_step,
)
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
    quality_verdict_evidence,
    verification_evidence,
)
from framework.harness.side_effects import (
    HarnessSideEffectApprovalRequest,
    HarnessSideEffectApprovalResolver,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
    HarnessSideEffectRegistry,
    HarnessSideEffectStorePort,
)
from framework.harness.workflow.binding_authority import (
    HarnessActivityCapabilities,
    HarnessActivityContractBinding,
    HarnessRuntimeBindingAuthority,
    HarnessWorkerBinding,
)
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.runtime_resolution import (
    HarnessGraphRuntimeResolver,
    HarnessResolvedRuntimeBindings,
)
from framework.harness.workflow.step import HarnessStepSpec, HarnessWorkerType
from framework.harness.workflow.spec import HarnessRouteKind
from framework.harness.workflow.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
)
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus

WorkerCallable = Callable[[dict[str, Any]], HarnessWorkerResult]

_ACTIVITY_RESULT_METADATA_KEYS = frozenset(
    {
        "activity_result_event_id",
        "worker_result_ref",
        "worker_status",
        "worker_result",
        "error_ref",
        "approval_granted",
        "approval_evidence_ref",
        "side_effect_decision_ref",
        "side_effect_effect_ref",
        "side_effect_intent_ref",
        "side_effect_outcome_ref",
        "side_effect_disposition",
    }
)
_SIDE_EFFECT_STATE_REF_KEYS = (
    "approval_evidence_ref",
    "side_effect_effect_ref",
    "side_effect_intent_ref",
    "side_effect_decision_ref",
    "side_effect_outcome_ref",
    "side_effect_disposition",
)

if TYPE_CHECKING:
    from framework.harness.ports import HarnessTransitionPort


@dataclass(frozen=True)
class HarnessRunResult:
    state: HarnessState
    decisions: tuple[HarnessDecision, ...]
    events: tuple[HarnessEvent, ...]
    worker_results: dict[str, HarnessWorkerResult]
    quality_verdicts: dict[str, HarnessQualityVerdict]
    side_effect_outcomes: dict[str, HarnessSideEffectOutcome] = field(
        default_factory=dict
    )

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


@dataclass(frozen=True)
class _PendingCompletionDecision:
    decision_type: HarnessDecisionType
    step_id: str | None
    authorization_projection: Mapping[str, Any]
    command_ordinal: int
    causation_id: str
    decided_at: Any
    history_cutoff_id: str | None


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
class _ActivityImplementationAdapter:
    activity_contract_id: str
    activity_contract_version: str
    event_port: Any
    capabilities: HarnessActivityCapabilities = HarnessActivityCapabilities(
        stable_idempotency=True,
    )

    def dispatch(self, request: dict[str, Any]) -> HarnessActivity:
        return self.event_port.create_activity(**request)


class InMemoryHarnessEventPort:
    """Explicit test-only sink; production composition must use a durable port."""

    def __init__(self) -> None:
        self.events: list[HarnessEvent] = []
        self.transitions: dict[str, list[HarnessTransitionCommitted]] = {}
        self.states: dict[str, HarnessState] = {}
        self.worker_results: dict[str, dict[str, HarnessWorkerResult]] = {}
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

    def commit_transition(
        self,
        previous: HarnessState | None,
        state: HarnessState,
        *,
        from_version: int,
        transition_kind: HarnessTransitionKind | str,
        occurred_at,
        decision=None,
        gate_results=None,
        budget=None,
        activity: HarnessActivity | None = None,
        activity_result_event_id: str | None = None,
    ) -> HarnessTransitionCommit:
        run_id = state.run_spec.run_id
        history = self.transitions.setdefault(run_id, [])
        if from_version != len(history):
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness transition attempted from a stale state version",
            )
        if previous is None:
            if run_id in self.states:
                raise EventReplayMismatchError(
                    sequence=len(self.events),
                    reason="Harness initialization attempted after state already exists",
                )
        else:
            current = self.states.get(run_id)
            if current is None or (
                HarnessStateProjection.from_state(current).checksum
                != HarnessStateProjection.from_state(previous).checksum
            ):
                raise EventReplayMismatchError(
                    sequence=len(self.events),
                    reason="Harness in-memory projection does not match committed state",
                )
        transition = HarnessTransitionCommitted.create(
            previous=previous,
            state=state,
            from_version=from_version,
            expected_last_sequence=len(self.events),
            transition_kind=transition_kind,
            occurred_at=occurred_at,
            decision=decision,
            gate_results=gate_results,
            budget=budget,
            activity_result_event_id=activity_result_event_id,
            activity_id=None if activity is None else activity.activity_id,
            idempotency_key=None if activity is None else activity.idempotency_key,
        )
        history.append(transition)
        self.states[run_id] = state
        self.events.append(
            HarnessEvent(
                event_id=transition.transition_id,
                event_type=HarnessEventType.TRANSITION_COMMITTED,
                run_id=run_id,
                step_id=state.current_step_id,
                payload=transition.to_payload(),
                occurred_at=transition.occurred_at,
            )
        )
        return HarnessTransitionCommit(
            state=state,
            transition=transition,
            stored_event=None,
        )

    def recover(self, run_spec: HarnessRunSpec) -> HarnessRecovery:
        state = self.states.get(run_spec.run_id)
        if state is not None and run_spec_checksum(state.run_spec) != run_spec_checksum(
            run_spec
        ):
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness run specification checksum mismatch",
            )
        results: dict[str, HarnessWorkerResult] = {}
        if state is not None:
            for step in state.step_states:
                activity = _activity_for_state_step(state, step.step_id)
                if activity is None:
                    continue
                result = self.activity_results.get(activity.activity_id)
                if result is not None:
                    results[step.step_id] = result
        transitions = tuple(self.transitions.get(run_spec.run_id, ()))
        return HarnessRecovery(
            state=state,
            state_version=len(transitions),
            expected_last_sequence=len(self.events),
            transitions=transitions,
            stored_events=(),
            worker_results=results,
            called_activity_ids=_in_memory_called_activity_ids(
                state=state,
                transitions=transitions,
                events=tuple(
                    event for event in self.events if event.run_id == run_spec.run_id
                ),
            ),
        )

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

    def resolve_replay_activity(
        self,
        state: HarnessState,
    ) -> tuple[ReplayActivityDescriptor, PayloadReference] | None:
        del state
        return None

    def record_activity_result(
        self,
        activity: HarnessActivity,
        result: HarnessWorkerResult,
        *,
        completed_at,
    ) -> HarnessEvent:
        results = self.worker_results.setdefault(activity.run_id, {})
        existing = self.activity_results.get(activity.activity_id)
        if existing is not None and existing.to_dict() != result.to_dict():
            raise EventReplayMismatchError(
                sequence=len(self.events),
                reason="Harness activity retry produced a different result",
            )
        self.activity_results[activity.activity_id] = result
        results[activity.step_id] = result
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
        graph_activity_dispatcher: HarnessGraphActivityDispatcherPort | None = None,
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
        self.runtime_binding_authority = runtime_binding_authority
        self.graph_preflight = graph_preflight or HarnessGraphPreflight(
            policy=HarnessGraphPreflightPolicy(),
        )
        graph_transition_port = (
            event_port if isinstance(event_port, HarnessGraphTransitionPort) else None
        )
        self.graph_transition_port = graph_transition_port
        self._graph_runtime = (
            None
            if graph_transition_port is None
            else HarnessGraphControlPlaneRuntime(
                graph_transition_port,
                activity_dispatcher=graph_activity_dispatcher,
            )
        )
        self._committed_events: list[HarnessEvent] = []
        self._state_versions: dict[str, int] = {}
        self._decision_indexes: dict[str, int] = {}
        self._recovered_worker_results: dict[str, HarnessWorkerResult] = {}
        self._recovered_gate_results: tuple[HarnessGateResult, ...] = ()
        self._recovered_quality_verdict: HarnessQualityVerdict | None = None
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
        self._pending_completion_decisions: dict[str, _PendingCompletionDecision] = {}
        self._prepared_graphs: dict[str, NormalizedHarnessGraph] = {}
        self._resolved_graph_bindings: dict[
            str,
            HarnessResolvedRuntimeBindings,
        ] = {}
        self._worker_bindings_by_run: dict[str, dict[str, HarnessWorkerBinding]] = {}
        self._activity_contract_versions_by_run: dict[str, dict[str, str]] = {}
        self._prepared_run_specs: dict[str, str] = {}

    def _require_graph_runtime(self) -> HarnessGraphControlPlaneRuntime:
        if self._graph_runtime is None:
            raise HarnessValidationError(
                "graph execution requires a durable graph transition port",
                code="graph_transition_port_missing",
            )
        return self._graph_runtime

    def _discard_prepared_graph_run(self, run_id: str) -> None:
        for cache in (
            self._gate_bindings_by_run,
            self._side_effect_bindings_by_run,
            self._terminal_side_effect_bindings,
            self._prepared_graphs,
            self._resolved_graph_bindings,
            self._worker_bindings_by_run,
            self._activity_contract_versions_by_run,
            self._prepared_run_specs,
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
        if (
            state.graph_ref.checksum
            != self._prepared_graphs[run_spec.run_id].checksum
        ):
            raise HarnessValidationError(
                "graph state does not match the pinned normalized graph",
                code="graph_control_graph_mismatch",
            )

    def _prepare_run_spec(self, run_spec: HarnessRunSpec) -> None:
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

        compile_result = self.graph_preflight.compiler.compile(run_spec.workflow)
        graph = compile_result.graph
        self.graph_preflight.validate_static(graph).raise_if_invalid()
        authority = self.runtime_binding_authority or self._legacy_runtime_authority(
            run_spec.workflow,
            graph,
        )
        resolved = HarnessGraphRuntimeResolver(authority).resolve(
            run_spec.workflow,
            graph,
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
        self._prepared_run_specs[run_spec.run_id] = spec_ref

    def _legacy_runtime_authority(
        self,
        workflow,
        graph: NormalizedHarnessGraph,
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
    ) -> HarnessState | HarnessGraphState:
        if run_spec.workflow.graph is not None:
            return self.initialize_graph(run_spec)
        self._prepare_run_spec(run_spec)
        recovery = self._restore_recovery(run_spec)
        if recovery.state is not None:
            return recovery.state
        state = HarnessState.initial(run_spec)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_CREATED,
                run_id=run_spec.run_id,
                occurred_at=run_spec.created_at,
            )
        )
        return self._commit_transition(
            None,
            state,
            transition_kind=HarnessTransitionKind.INITIALIZE,
            occurred_at=run_spec.created_at,
        )

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

    def recover_graph(self, run_spec: HarnessRunSpec) -> HarnessGraphState:
        self._prepare_run_spec(run_spec)
        return self._require_graph_runtime().recover(
            run_spec.run_id,
            self._prepared_graphs[run_spec.run_id],
            run_spec_checksum=self._prepared_run_specs[run_spec.run_id],
        )

    def run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        if run_spec.workflow.graph is not None:
            raise HarnessValidationError(
                "explicit Graph execution awaits the Sequence/Choice cutover",
                code="graph_execution_not_active",
            )
        state = self.initialize(run_spec)
        if not isinstance(state, HarnessState):  # pragma: no cover - guarded above
            raise AssertionError("legacy run initialized graph state")
        recovery = self._restore_recovery(run_spec)
        return self._drive(
            state,
            worker_result=recovery.current_worker_result,
            initial_gate_results=self._recovered_gate_results,
            initial_quality_verdict=self._recovered_quality_verdict,
        )

    def recover_and_run(self, run_spec: HarnessRunSpec) -> HarnessRunResult:
        if run_spec.workflow.graph is not None:
            raise HarnessValidationError(
                "explicit Graph execution awaits the Sequence/Choice cutover",
                code="graph_execution_not_active",
            )
        recovery = self._restore_recovery(run_spec)
        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "Harness run has no committed recoverable state"
            )
        return self._drive(
            recovery.state,
            worker_result=recovery.current_worker_result,
            initial_gate_results=self._recovered_gate_results,
            initial_quality_verdict=self._recovered_quality_verdict,
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
        recovery = self._restore_recovery(run_spec)
        if recovery.state is None:
            raise EventIncompleteHistoryError(
                "Harness approval resume requires committed recoverable state"
            )
        state = recovery.state
        if supplied_state is not None and (
            HarnessStateProjection.from_state(supplied_state).checksum
            != HarnessStateProjection.from_state(state).checksum
        ):
            raise EventReplayMismatchError(
                sequence=recovery.expected_last_sequence,
                reason="supplied Harness state does not match durable history",
            )
        if state.status != HarnessRunStatus.WAITING_APPROVAL:
            raise HarnessValidationError("Harness run is not waiting for approval")
        step_id = state.current_step_id
        if step_id is None:
            raise HarnessValidationError(
                "approval-waiting Harness run requires current_step_id"
            )
        if not approved:
            decision = HarnessDecision(
                decision_type=HarnessDecisionType.CANCEL_RUN,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                reason=reason or "Harness approval was cancelled",
                payload={"approval_outcome": "cancelled"},
            )
            replay_activity = _resolve_replay_activity_binding(
                self.event_port,
                state,
            )
            decision_input = self._decision_input(
                state,
                gate_results=(),
                quality_verdict=None,
                expected_activity=(
                    None if replay_activity is None else replay_activity[0]
                ),
                approval_outcome="cancelled",
            )
            self._record_decision(
                decision,
                decision_input=decision_input,
                replay_activity=replay_activity,
            )
            transition_time = _next_transition_time(state)
            self._quarantine_prepared_side_effects(state)
            cancelled = transition_step(
                state,
                step_id,
                HarnessStepStatus.HALTED,
                error=decision.reason,
                current_step_id=step_id,
                at=transition_time,
            )
            cancelled = transition_run(
                cancelled,
                HarnessRunStatus.CANCELLED,
                metadata={"terminal_reason": decision.reason},
                at=transition_time,
            )
            cancelled = self._commit_transition(
                state,
                cancelled,
                transition_kind=HarnessTransitionKind.APPROVAL_CANCEL,
                occurred_at=transition_time,
                decision=decision,
            )
            self._record_step_change(
                state,
                cancelled,
                step_id,
                transition_kind="approval_cancel",
            )
            self._record_state_change(
                state,
                cancelled,
                transition_kind="approval_cancel",
            )
            return self._result(cancelled, decisions=[decision])

        step_spec = _get_step_spec(state, step_id)
        if step_spec.side_effect_handler is not None and (
            not isinstance(approval_ref, str) or not approval_ref.strip()
        ):
            raise HarnessValidationError(
                "effectful approval resume requires an opaque durable approval ref",
                code="side_effect_approval_ref_required",
                details={
                    "code": "side_effect_approval_ref_required",
                    "step_id": step_id,
                },
            )

        # Recovery may have only an integrity summary for the worker activity.
        # Prove the complete recorded result is available before committing any
        # approval-resume transition; otherwise fail closed at the old state.
        worker_result = recovery.current_worker_result
        if worker_result is None:
            raise EventIncompleteHistoryError(
                "approval resume requires a committed worker activity result"
            )
        decision = HarnessDecision(
            decision_type=HarnessDecisionType.RESUME_AFTER_APPROVAL,
            run_id=state.run_spec.run_id,
            step_id=step_id,
            reason=reason or "Harness approval granted",
            payload={"approval_outcome": "approved"},
        )
        replay_activity = _resolve_replay_activity_binding(
            self.event_port,
            state,
        )
        decision_input = self._decision_input(
            state,
            gate_results=(),
            quality_verdict=None,
            expected_activity=(None if replay_activity is None else replay_activity[0]),
            approval_outcome="approved",
        )
        self._record_decision(
            decision,
            decision_input=decision_input,
            replay_activity=replay_activity,
        )
        transition_time = _next_transition_time(state)
        resumed = transition_run(
            state,
            HarnessRunStatus.RUNNING,
            at=transition_time,
        )
        resumed = transition_step(
            resumed,
            step_id,
            HarnessStepStatus.RUNNING,
            metadata={
                "approval_granted": True,
                **(
                    {}
                    if approval_ref is None
                    else {"approval_evidence_ref": approval_ref.strip()}
                ),
            },
            current_step_id=step_id,
            at=transition_time,
        )
        resumed = self._commit_transition(
            state,
            resumed,
            transition_kind=HarnessTransitionKind.APPROVAL_RESUME,
            occurred_at=transition_time,
            decision=decision,
        )
        self._record_state_change(
            state,
            resumed,
            transition_kind="approval_resume",
        )
        self._record_step_change(
            state,
            resumed,
            step_id,
            transition_kind="approval_resume",
        )
        return self._drive(
            resumed,
            initial_decisions=[decision],
            worker_result=worker_result,
        )

    def _drive(
        self,
        state: HarnessState,
        *,
        initial_decisions: list[HarnessDecision] | None = None,
        worker_result: HarnessWorkerResult | None = None,
        initial_gate_results: tuple[HarnessGateResult, ...] = (),
        initial_quality_verdict: HarnessQualityVerdict | None = None,
    ) -> HarnessRunResult:
        decisions: list[HarnessDecision] = list(initial_decisions or ())
        worker_results: dict[str, HarnessWorkerResult] = {}
        quality_verdicts: dict[str, HarnessQualityVerdict] = {}
        if initial_quality_verdict is not None and state.current_step_id is not None:
            quality_verdicts[state.current_step_id] = initial_quality_verdict
        gate_results = initial_gate_results
        quality_verdict = initial_quality_verdict

        while state.status not in _run_loop_stop_statuses():
            pending_completion = self._pending_completion_decisions.get(
                state.run_spec.run_id
            )
            replay_activity = _resolve_replay_activity_binding(
                self.event_port,
                state,
            )
            decision_input = self._decision_input(
                state,
                gate_results=gate_results,
                quality_verdict=quality_verdict,
                expected_activity=(
                    None if replay_activity is None else replay_activity[0]
                ),
                command_ordinal=(
                    None
                    if pending_completion is None
                    else pending_completion.command_ordinal
                ),
                causation_id=(
                    None
                    if pending_completion is None
                    else pending_completion.causation_id
                ),
            )
            decision = self.scheduler.next_decision(
                state,
                worker_result=worker_result,
                quality_verdict=quality_verdict,
                gate_results=gate_results,
            )
            if pending_completion is not None:
                if (
                    decision.decision_type is not pending_completion.decision_type
                    or decision.step_id != pending_completion.step_id
                ):
                    raise EventReplayMismatchError(
                        sequence=pending_completion.command_ordinal,
                        reason="dangling side-effect decision conflicts with recovered scheduler state",
                    )
                decision = replace(decision, decided_at=pending_completion.decided_at)
            prepared_side_effect = self._prepare_completion_side_effect(
                state,
                decision=decision,
                decision_input=decision_input,
                worker_result=worker_result,
                gate_results=gate_results,
                quality_verdict=quality_verdict,
            )
            if prepared_side_effect is not None:
                authorization_projection = _side_effect_authorization_projection(
                    prepared_side_effect.authorization
                )
                decision = replace(
                    decision,
                    payload={
                        **decision.payload,
                        "side_effect_authorization": authorization_projection,
                    },
                )
                decision_input = self._decision_input(
                    state,
                    gate_results=gate_results,
                    quality_verdict=quality_verdict,
                    expected_activity=(
                        None if replay_activity is None else replay_activity[0]
                    ),
                    side_effect_authorization=authorization_projection,
                    command_ordinal=(
                        None
                        if pending_completion is None
                        else pending_completion.command_ordinal
                    ),
                    causation_id=(
                        None
                        if pending_completion is None
                        else pending_completion.causation_id
                    ),
                )
            if pending_completion is not None:
                if prepared_side_effect is None or (
                    normalize_canonical_json(
                        authorization_projection,
                        path="$.harness_side_effect_authorization.recomputed",
                    )
                    != normalize_canonical_json(
                        pending_completion.authorization_projection,
                        path="$.harness_side_effect_authorization.recorded",
                    )
                ):
                    raise EventReplayMismatchError(
                        sequence=pending_completion.command_ordinal,
                        reason="dangling side-effect authorization cannot be reconstructed exactly",
                    )
            else:
                self._record_decision(
                    decision,
                    decision_input=decision_input,
                    replay_activity=replay_activity,
                )
            decisions.append(decision)

            if decision.decision_type == HarnessDecisionType.START_STEP:
                state = self._start_run(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.PLAN_STEP:
                state, gate_results = self._plan_step(state, decision)
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.EXECUTE_STEP:
                state, worker_result = self._execute_step(state, decision)
                worker_results[decision.step_id or ""] = worker_result
                gate_results = ()
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.VERIFY_STEP:
                state, gate_results, quality_verdict = self._verify_step(
                    state, decision, worker_result
                )
                if quality_verdict is not None:
                    quality_verdicts[decision.step_id or ""] = quality_verdict
            elif decision.decision_type == HarnessDecisionType.COMPLETE_STEP:
                try:
                    state = self._complete_step(
                        state,
                        decision,
                        worker_result,
                        gate_results=gate_results,
                        quality_verdict=quality_verdict,
                        prepared_side_effect=prepared_side_effect,
                    )
                except HarnessValidationError as exc:
                    if exc.code != "effect_retry_exhausted":
                        raise
                    state, failure_decision = self._fail_side_effect_completion(
                        state,
                        completion_decision=decision,
                        prepared_side_effect=prepared_side_effect,
                        gate_results=gate_results,
                        quality_verdict=quality_verdict,
                        replay_activity=replay_activity,
                    )
                    decisions.append(failure_decision)
                gate_results = ()
            elif decision.decision_type == HarnessDecisionType.ROUTE_TO_STEP:
                state = self._route_to_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.ROUTE_TO_REPAIR:
                state = self._route_to_repair(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.RETRY_STEP:
                state = self._retry_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.REPLAN_STEP:
                state = self._replan_step(state, decision)
                gate_results = ()
                worker_result = None
                quality_verdict = None
            elif decision.decision_type == HarnessDecisionType.WAIT_FOR_APPROVAL:
                state = self._wait_for_approval(state, decision)
                gate_results = ()
            elif decision.decision_type == HarnessDecisionType.COMPLETE_RUN:
                try:
                    state = self._complete_terminal_side_effect(
                        state,
                        decision,
                        prepared_side_effect=prepared_side_effect,
                    )
                except HarnessValidationError as exc:
                    if exc.code != "effect_retry_exhausted":
                        raise
                    state, failure_decision = self._fail_side_effect_completion(
                        state,
                        completion_decision=decision,
                        prepared_side_effect=prepared_side_effect,
                        gate_results=gate_results,
                        quality_verdict=quality_verdict,
                        replay_activity=replay_activity,
                    )
                    decisions.append(failure_decision)
                else:
                    state = self._finish_run(
                        state, HarnessRunStatus.SUCCEEDED, decision
                    )
            elif decision.decision_type == HarnessDecisionType.FAIL_RUN:
                state = self._finish_run(state, HarnessRunStatus.FAILED, decision)
            elif decision.decision_type == HarnessDecisionType.HALT_RUN:
                state = self._finish_run(state, HarnessRunStatus.HALTED, decision)
            elif decision.decision_type == HarnessDecisionType.BLOCK_RUN:
                state = self._finish_run(state, HarnessRunStatus.BLOCKED, decision)
            elif decision.decision_type == HarnessDecisionType.CANCEL_RUN:
                state = self._finish_run(state, HarnessRunStatus.CANCELLED, decision)
            else:
                state = self._finish_run(state, HarnessRunStatus.FAILED, decision)

            if pending_completion is not None:
                self._pending_completion_decisions.pop(state.run_spec.run_id, None)

        return self._result(
            state,
            decisions=decisions,
            worker_results=worker_results,
            quality_verdicts=quality_verdicts,
        )

    def _start_run(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        if state.status == HarnessRunStatus.CREATED:
            previous = state
            transition_time = _next_transition_time(state)
            candidate = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
            state = self._commit_transition(
                state,
                candidate,
                transition_kind=HarnessTransitionKind.RUN_START,
                occurred_at=transition_time,
                decision=decision,
            )
            self._record_state_change(
                previous,
                state,
                transition_kind="run_start",
            )
        return state

    def _plan_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, tuple[HarnessGateResult, ...]]:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.RUNNING, HarnessRunStatus.REPLANNING}:
            state = transition_run(
                state,
                HarnessRunStatus.PLANNING,
                at=transition_time,
            )
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.PLANNING,
            turn_increment=1,
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.PLAN_ENTRY,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="plan_entry")
        self._record_step_change(previous, state, step_id, transition_kind="plan_entry")
        self._record_phase(
            state,
            HarnessPhase.PLAN,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.ENTRY,
        )
        gate_results = self._evaluate_gates(
            self.plan_gates, state, step_id, worker_result=None, quality_verdict=None
        )
        state = self._commit_plan_exit(
            state,
            step_id=step_id,
            gate_results=gate_results,
            record_observations=True,
        )
        return state, gate_results

    def _commit_plan_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if all(result.passed for result in gate_results):
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.PLAN_VERIFIED,
                current_step_id=step_id,
                at=transition_time,
            )
        else:
            state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.PLAN_EXIT,
            occurred_at=transition_time,
            gate_results=gate_results,
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.PLAN,
                step_id,
                gate_results,
                boundary=HarnessPhaseBoundary.EXIT,
            )
            if (
                get_step_state(previous, step_id).status
                != get_step_state(state, step_id).status
            ):
                self._record_step_change(
                    previous,
                    state,
                    step_id,
                    transition_kind="plan_exit",
                )
        return state

    def _execute_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
    ) -> tuple[HarnessState, HarnessWorkerResult]:
        step_id = _require_step(decision)
        self.event_port.require_activity_storage()
        step_spec = _get_step_spec(state, step_id)
        step_state = get_step_state(state, step_id)
        task = self._worker_task(step_spec, state)
        contract_version = self._activity_contract_versions_by_run.get(
            state.run_spec.run_id,
            {},
        ).get(step_id)
        if contract_version is None:
            raise HarnessValidationError(
                "activity contract binding is unavailable",
                code="unknown_runtime_activity_binding",
                details={
                    "code": "unknown_runtime_activity_binding",
                    "step_id": step_id,
                },
            )
        activity = self.event_port.create_activity(
            run_id=state.run_spec.run_id,
            step_id=step_id,
            attempt=step_state.attempts + 1,
            activity_type=step_spec.worker_type.value,
            inputs=task,
            contract_version=contract_version,
            worker_version=str(step_spec.metadata.get("worker_version", "1")),
        )
        activity_metadata = {
            "activity_id": activity.activity_id,
            "activity_type": activity.activity_type,
            "activity_contract_version": activity.contract_version,
            "activity_idempotency_key": activity.idempotency_key,
            "activity_input_checksum": activity.input_checksum,
            "activity_worker_version": activity.worker_version,
            "activity_attempt": activity.attempt,
        }
        if activity.identity_scope_ref is not None:
            activity_metadata["activity_identity_scope_ref"] = (
                activity.identity_scope_ref
            )
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {
            HarnessRunStatus.PLANNING,
            HarnessRunStatus.RUNNING,
            HarnessRunStatus.EXECUTING,
        }:
            if state.status != HarnessRunStatus.EXECUTING:
                state = transition_run(
                    state,
                    HarnessRunStatus.EXECUTING,
                    at=transition_time,
                )
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.RUNNING,
            attempts=step_state.attempts + 1,
            turn_increment=1,
            worker_call_increment=1,
            metadata=activity_metadata,
            metadata_remove=_ACTIVITY_RESULT_METADATA_KEYS,
            clear_output_ref=True,
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.EXECUTE_ENTRY,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="execute_entry")
        self._record_step_change(
            previous, state, step_id, transition_kind="execute_entry"
        )
        self._record_phase(
            state,
            HarnessPhase.EXECUTE,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.ENTRY,
        )

        started_at = _next_transition_time(state)
        worker_result = self.event_port.accept_activity(
            activity,
            task,
            accepted_at=state.updated_at,
            started_at=started_at,
        )
        if worker_result is None:
            worker_result = self._call_worker(
                step_spec,
                state,
                task=task,
                activity=activity,
                started_at=started_at,
            )
        else:
            worker_result = _coerce_worker_result(worker_result)
        activity_result_event_id = self._record_activity_result(
            state,
            step_id=step_id,
            activity=activity,
            worker_result=worker_result,
        )
        state = self._commit_worker_result_transitions(
            state,
            step_id=step_id,
            step_spec=step_spec,
            worker_result=worker_result,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=None,
        )
        return state, worker_result

    def _record_activity_result(
        self,
        state: HarnessState,
        *,
        step_id: str,
        activity: HarnessActivity,
        worker_result: HarnessWorkerResult,
    ) -> str:
        activity_result_event = self.event_port.record_activity_result(
            activity,
            worker_result,
            completed_at=_next_transition_time(state),
        )
        if not isinstance(activity_result_event, HarnessEvent):
            raise HarnessValidationError(
                "Harness transition port returned an invalid activity result projection"
            )
        if (
            activity_result_event.event_id != activity.result_event_id
            or activity_result_event.event_type
            != HarnessEventType.WORKER_RESULT_RECORDED
            or activity_result_event.run_id != state.run_spec.run_id
            or activity_result_event.step_id != step_id
        ):
            raise HarnessValidationError(
                "Harness transition port returned a conflicting activity result projection"
            )
        if not any(
            event.event_id == activity_result_event.event_id
            for event in self._committed_events
        ):
            self._committed_events.append(activity_result_event)
        return str(activity_result_event.event_id)

    def _commit_worker_result_transitions(
        self,
        state: HarnessState,
        *,
        step_id: str,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        state = self._commit_worker_result_transition(
            state,
            step_id=step_id,
            step_spec=step_spec,
            worker_result=worker_result,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=decision,
        )
        return self._commit_execute_exit_transition(
            state,
            step_id=step_id,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
            decision=decision,
        )

    def _commit_worker_result_transition(
        self,
        state: HarnessState,
        *,
        step_id: str,
        step_spec: HarnessStepSpec,
        worker_result: HarnessWorkerResult,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace_step_state(
            state,
            replace(
                get_step_state(state, step_id),
                output_ref=step_spec.output_key
                if worker_result.status == HarnessWorkerStatus.SUCCEEDED
                else None,
                error=worker_result.error,
                metadata={
                    **get_step_state(state, step_id).metadata,
                    "activity_result_event_id": activity_result_event_id,
                    "worker_result_ref": checksum_for(worker_result.to_dict()),
                    "worker_status": worker_result.status.value,
                    "worker_result": worker_result.to_dict(),
                },
                updated_at=transition_time,
            ),
            current_step_id=step_id,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.WORKER_RESULT_COMMITTED,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        return state

    def _commit_execute_exit_transition(
        self,
        state: HarnessState,
        *,
        step_id: str,
        activity: HarnessActivity,
        activity_result_event_id: str,
        decision: HarnessDecision | None,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.EXECUTE_EXIT,
            occurred_at=transition_time,
            decision=decision,
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        self._record_phase(
            state,
            HarnessPhase.EXECUTE,
            step_id,
            (),
            boundary=HarnessPhaseBoundary.EXIT,
        )
        return state

    def _verify_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
    ) -> tuple[
        HarnessState, tuple[HarnessGateResult, ...], HarnessQualityVerdict | None
    ]:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.RUNNING}:
            state = transition_run(
                state,
                HarnessRunStatus.VERIFYING,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        if step_state.status == HarnessStepStatus.RUNNING:
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.VERIFYING,
                current_step_id=step_id,
                turn_increment=1,
                at=transition_time,
            )
        else:
            state = replace_step_state(
                state,
                step_state,
                current_step_id=step_id,
                turn_increment=1,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.VERIFY_ENTRY,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="verify_entry")
        self._record_step_change(
            previous, state, step_id, transition_kind="verify_entry"
        )
        self._record_phase(
            state, HarnessPhase.VERIFY, step_id, (), boundary=HarnessPhaseBoundary.ENTRY
        )
        gate_entries = self._verify_gate_entries(state, step_id)
        gate_results = self._evaluate_gates(
            tuple(gate for _, gate in gate_entries),
            state,
            step_id,
            worker_result=worker_result,
            quality_verdict=None,
            gate_references=tuple(reference for reference, _ in gate_entries),
        )
        quality_verdict = self._quality_verdict(state, step_id, gate_results)
        state = self._commit_verify_exit(
            state,
            step_id=step_id,
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            record_observations=True,
        )
        return state, gate_results, quality_verdict

    def _commit_verify_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.VERIFY_EXIT,
            occurred_at=transition_time,
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.VERIFY,
                step_id,
                gate_results,
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _complete_step(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        worker_result: HarnessWorkerResult | None,
        *,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        prepared_side_effect: _PreparedSideEffect | None,
    ) -> HarnessState:
        step_id = _require_step(decision)
        del gate_results, quality_verdict
        side_effect_outcome = (
            None
            if prepared_side_effect is None
            else self._execute_prepared_side_effect(prepared_side_effect)
        )
        previous = state
        transition_time = _next_transition_time(previous)
        side_effect_metadata: dict[str, Any] = {}
        if side_effect_outcome is not None:
            assert prepared_side_effect is not None
            side_effect_metadata = {
                "approval_evidence_ref": (
                    prepared_side_effect.authorization.approval_evidence_ref
                ),
                "side_effect_effect_ref": checksum_for(side_effect_outcome.effect_id),
                "side_effect_intent_ref": self._side_effect_intents[
                    state.run_spec.run_id
                ][step_id].checksum,
                "side_effect_decision_ref": side_effect_outcome.decision_ref,
                "side_effect_outcome_ref": side_effect_outcome.checksum,
                "side_effect_disposition": side_effect_outcome.disposition.value,
            }
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.SUCCEEDED,
            metadata={
                "worker_result": worker_result.to_dict()
                if worker_result is not None
                else None,
                **side_effect_metadata,
            },
            current_step_id=step_id,
            at=transition_time,
        )
        state = _merge_outputs(state, step_id, worker_result)
        if state.status == HarnessRunStatus.VERIFYING:
            state = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.STEP_SUCCESS,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        self._record_step_change(
            previous, state, step_id, transition_kind="step_success"
        )
        if previous.status != state.status:
            self._record_state_change(
                previous, state, transition_kind="verify_complete"
            )
        return state

    def _prepare_completion_side_effect(
        self,
        state: HarnessState,
        *,
        decision: HarnessDecision,
        decision_input: Mapping[str, Any],
        worker_result: HarnessWorkerResult | None,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
    ) -> _PreparedSideEffect | None:
        if decision.decision_type is HarnessDecisionType.COMPLETE_STEP:
            step_id = _require_step(decision)
            return self._prepare_worker_side_effect(
                state,
                scheduler_decision=decision,
                decision_input=decision_input,
                step_id=step_id,
                worker_result=worker_result,
                gate_results=gate_results,
                quality_verdict=quality_verdict,
            )
        if decision.decision_type is HarnessDecisionType.COMPLETE_RUN:
            return self._prepare_terminal_side_effect(
                state,
                scheduler_decision=decision,
                decision_input=decision_input,
            )
        return None

    def _prepare_worker_side_effect(
        self,
        state: HarnessState,
        *,
        scheduler_decision: HarnessDecision,
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
            decided_at=scheduler_decision.decided_at,
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

    def _route_to_step(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        target_step_id = (
            decision.target_step_id or state.run_spec.workflow.entry_step_id
        )
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = transition_run(
                state,
                HarnessRunStatus.RUNNING,
                at=transition_time,
            )
        step_state = get_step_state(state, target_step_id)
        if step_state.status == HarnessStepStatus.PENDING:
            state = replace(
                state,
                current_step_id=target_step_id,
                updated_at=transition_time,
            )
        else:
            reset_step = replace(
                step_state,
                status=HarnessStepStatus.PENDING,
                error=None,
                metadata={**step_state.metadata, "rerouted": True},
                updated_at=transition_time,
            )
            state = replace_step_state(
                state,
                reset_step,
                current_step_id=target_step_id,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.ROUTE_TO_STEP,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="route_to_step")
        if get_step_state(previous, target_step_id) != get_step_state(
            state, target_step_id
        ):
            self._record_step_change(
                previous,
                state,
                target_step_id,
                transition_kind="route_to_step",
            )
        return state

    def _route_to_repair(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if decision.step_id:
            candidate = _fail_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        if state.status in {HarnessRunStatus.EXECUTING, HarnessRunStatus.VERIFYING}:
            state = transition_run(state, HarnessRunStatus.RUNNING, at=transition_time)
        target_step_id = (
            decision.target_step_id or state.run_spec.workflow.entry_step_id
        )
        target = get_step_state(state, target_step_id)
        if target.status != HarnessStepStatus.PENDING:
            target = replace(
                target,
                status=HarnessStepStatus.PENDING,
                error=None,
                metadata={**target.metadata, "rerouted": True},
                updated_at=transition_time,
            )
            state = replace_step_state(
                state,
                target,
                current_step_id=target_step_id,
                at=transition_time,
            )
        else:
            state = replace(
                state,
                current_step_id=target_step_id,
                updated_at=transition_time,
            )
        state = replace(
            state,
            metadata={**state.metadata, "repair_from_step_id": decision.step_id},
            updated_at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.ROUTE_TO_REPAIR,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(
                previous, state, transition_kind="route_to_repair"
            )
        if decision.step_id and get_step_state(
            previous, decision.step_id
        ) != get_step_state(state, decision.step_id):
            self._record_step_change(
                previous,
                state,
                decision.step_id,
                transition_kind="route_to_repair",
            )
        if get_step_state(previous, target_step_id) != get_step_state(
            state, target_step_id
        ):
            self._record_step_change(
                previous,
                state,
                target_step_id,
                transition_kind="route_to_repair",
            )
        return state

    def _retry_step(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.RETRYING,
            current_step_id=step_id,
            error=decision.reason,
            at=transition_time,
        )
        if state.status != HarnessRunStatus.EXECUTING:
            state = transition_run(
                state,
                HarnessRunStatus.EXECUTING,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.RETRY,
            occurred_at=transition_time,
            decision=decision,
        )
        self._record_step_change(previous, state, step_id, transition_kind="retry")
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="retry")
        return state

    def _replan_step(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {HarnessRunStatus.PLANNING, HarnessRunStatus.VERIFYING}:
            state = transition_run(
                state,
                HarnessRunStatus.REPLANNING,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        state = transition_step(
            state,
            step_id,
            HarnessStepStatus.REPLANNING,
            replans=step_state.replans + 1,
            replan_increment=1,
            current_step_id=step_id,
            error=decision.reason,
            at=transition_time,
        )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.REPLAN_ENTRY,
            occurred_at=transition_time,
            decision=decision,
        )
        if previous.status != state.status:
            self._record_state_change(previous, state, transition_kind="replan")
        self._record_step_change(previous, state, step_id, transition_kind="replan")
        self._record_phase(
            state, HarnessPhase.REPLAN, step_id, (), boundary=HarnessPhaseBoundary.ENTRY
        )
        return self._commit_replan_exit(
            state,
            step_id=step_id,
            record_observations=True,
        )

    def _commit_replan_exit(
        self,
        state: HarnessState,
        *,
        step_id: str,
        record_observations: bool,
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        state = replace(state, updated_at=transition_time)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.REPLAN_EXIT,
            occurred_at=transition_time,
        )
        if record_observations:
            self._record_phase(
                state,
                HarnessPhase.REPLAN,
                step_id,
                (),
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _wait_for_approval(
        self, state: HarnessState, decision: HarnessDecision
    ) -> HarnessState:
        step_id = _require_step(decision)
        previous = state
        transition_time = _next_transition_time(previous)
        if state.status in {
            HarnessRunStatus.RUNNING,
            HarnessRunStatus.EXECUTING,
            HarnessRunStatus.VERIFYING,
        }:
            state = transition_run(
                state,
                HarnessRunStatus.WAITING_APPROVAL,
                at=transition_time,
            )
        step_state = get_step_state(state, step_id)
        if step_state.status != HarnessStepStatus.WAITING_APPROVAL:
            state = transition_step(
                state,
                step_id,
                HarnessStepStatus.WAITING_APPROVAL,
                error=decision.reason,
                at=transition_time,
            )
        state = self._commit_transition(
            previous,
            state,
            transition_kind=HarnessTransitionKind.WAIT_FOR_APPROVAL,
            occurred_at=transition_time,
            decision=decision,
            activity=_activity_for_state_step(state, step_id),
            activity_result_event_id=_activity_result_event_id(state, step_id),
        )
        if previous.status != state.status:
            self._record_state_change(
                previous, state, transition_kind="wait_for_approval"
            )
        if (
            get_step_state(previous, step_id).status
            != get_step_state(state, step_id).status
        ):
            self._record_step_change(
                previous,
                state,
                step_id,
                transition_kind="wait_for_approval",
            )
        return state

    def _prepare_terminal_side_effect(
        self,
        state: HarnessState,
        *,
        scheduler_decision: HarnessDecision,
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
        if any(
            step.status is not HarnessStepStatus.SUCCEEDED for step in state.step_states
        ):
            raise HarnessValidationError(
                "terminal side effect requires every step outcome to be durable and successful",
                code="terminal_side_effect_steps_incomplete",
            )
        run_id = state.run_spec.run_id
        state_checksum = HarnessStateProjection.from_state(state).checksum
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
            payload={
                "prepared_outcome_refs": [outcome.checksum for outcome in prepared],
                "history_cutoff": self._terminal_history_cutoff(run_id),
            },
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
            decided_at=scheduler_decision.decided_at,
        )
        return _PreparedSideEffect(
            slot="__terminal__",
            intent=intent,
            authorization=authorization,
            binding=binding,
            prepare=False,
        )

    def _terminal_history_cutoff(self, run_id: str) -> str | None:
        pending = self._pending_completion_decisions.get(run_id)
        if (
            pending is not None
            and pending.decision_type is HarnessDecisionType.COMPLETE_RUN
        ):
            return pending.history_cutoff_id
        return (
            None if not self._committed_events else self._committed_events[-1].event_id
        )

    def _complete_terminal_side_effect(
        self,
        state: HarnessState,
        decision: HarnessDecision,
        *,
        prepared_side_effect: _PreparedSideEffect | None,
    ) -> HarnessState:
        policy = state.run_spec.workflow.terminal_side_effect_policy
        if policy is None:
            if prepared_side_effect is not None:
                raise HarnessValidationError(
                    "legacy workflow cannot execute a terminal side effect"
                )
            return state
        if prepared_side_effect is None or prepared_side_effect.slot != "__terminal__":
            raise HarnessValidationError(
                "terminal completion is missing its recorded side-effect authorization",
                code="terminal_side_effect_policy_missing",
            )
        del decision
        self._execute_prepared_side_effect(prepared_side_effect)
        return state

    def _fail_side_effect_completion(
        self,
        state: HarnessState,
        *,
        completion_decision: HarnessDecision,
        prepared_side_effect: _PreparedSideEffect | None,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        replay_activity: tuple[ReplayActivityDescriptor, PayloadReference] | None,
    ) -> tuple[HarnessState, HarnessDecision]:
        if prepared_side_effect is None:
            raise HarnessValidationError(
                "side-effect retry exhaustion has no matching authorization",
                code="side_effect_authorization_missing",
            )
        failure = {
            "code": "effect_retry_exhausted",
            "effect_ref": checksum_for(prepared_side_effect.intent.effect_id),
        }
        failure_decision = HarnessDecision(
            decision_type=HarnessDecisionType.FAIL_RUN,
            run_id=state.run_spec.run_id,
            step_id=state.current_step_id,
            reason="side-effect failure: effect_retry_exhausted",
            payload={"side_effect_failure": failure},
            decided_at=completion_decision.decided_at,
        )
        decision_input = self._decision_input(
            state,
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            expected_activity=(None if replay_activity is None else replay_activity[0]),
            side_effect_failure=failure,
        )
        self._record_decision(
            failure_decision,
            decision_input=decision_input,
            replay_activity=replay_activity,
        )
        self._quarantine_prepared_side_effects(state)
        return (
            self._finish_run(state, HarnessRunStatus.FAILED, failure_decision),
            failure_decision,
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

    def _finish_run(
        self, state: HarnessState, status: HarnessRunStatus, decision: HarnessDecision
    ) -> HarnessState:
        previous = state
        transition_time = _next_transition_time(previous)
        if status is not HarnessRunStatus.SUCCEEDED:
            self._quarantine_prepared_side_effects(state)
        if status == HarnessRunStatus.HALTED and decision.step_id:
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.ENTRY,
            )
            candidate = _halt_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        if status == HarnessRunStatus.FAILED and decision.step_id:
            candidate = _fail_current_step(
                state,
                decision.step_id,
                decision.reason,
                at=transition_time,
            )
            if candidate is not state:
                state = candidate
        terminal_metadata: dict[str, Any] = {}
        terminal_outcome = self._side_effect_outcomes.get(
            state.run_spec.run_id, {}
        ).get("__terminal__")
        if status is HarnessRunStatus.SUCCEEDED and terminal_outcome is not None:
            terminal_metadata = {
                "terminal_side_effect_effect_ref": checksum_for(
                    terminal_outcome.effect_id
                ),
                "terminal_side_effect_decision_ref": terminal_outcome.decision_ref,
                "terminal_side_effect_outcome_ref": terminal_outcome.checksum,
                "terminal_side_effect_disposition": terminal_outcome.disposition.value,
            }
        state = transition_run(
            state,
            status,
            metadata={"terminal_reason": decision.reason, **terminal_metadata},
            at=transition_time,
        )
        transition_kind = _terminal_transition_kind(status, decision)
        state = self._commit_transition(
            previous,
            state,
            transition_kind=transition_kind,
            occurred_at=transition_time,
            decision=decision,
            activity=(
                None
                if decision.step_id is None
                else _activity_for_state_step(state, decision.step_id)
            ),
            activity_result_event_id=(
                None
                if decision.step_id is None
                else _activity_result_event_id(state, decision.step_id)
            ),
        )
        if decision.step_id and get_step_state(
            previous, decision.step_id
        ) != get_step_state(state, decision.step_id):
            self._record_step_change(
                previous,
                state,
                decision.step_id,
                transition_kind=transition_kind.value,
            )
        self._record_state_change(
            previous,
            state,
            transition_kind=transition_kind.value,
        )
        if status == HarnessRunStatus.HALTED and decision.step_id:
            self._record_phase(
                state,
                HarnessPhase.HALT,
                decision.step_id,
                (),
                boundary=HarnessPhaseBoundary.EXIT,
            )
        return state

    def _evaluate_gates(
        self,
        gates: tuple[DeterministicGate, ...],
        state: HarnessState,
        step_id: str,
        *,
        worker_result: HarnessWorkerResult | None,
        quality_verdict: HarnessQualityVerdict | None,
        record_events: bool = True,
        gate_references: tuple[str, ...] | None = None,
    ) -> tuple[HarnessGateResult, ...]:
        step_spec = _get_step_spec(state, step_id)
        context = GateContext(
            state=state,
            step_spec=step_spec,
            step_state=get_step_state(state, step_id),
            worker_result=worker_result,
            quality_verdict=quality_verdict,
            budget=self._budget_snapshot(state, worker_result),
        )
        references = gate_references or tuple(_gate_reference(gate) for gate in gates)
        if len(references) != len(gates):
            raise HarnessValidationError(
                "gate references must match gate implementations"
            )
        results = tuple(
            self._evaluate_gate(
                gate,
                reference=reference,
                context=context,
            )
            for gate, reference in zip(gates, references, strict=True)
        )
        if record_events:
            for result in results:
                self._record_event(
                    HarnessEvent(
                        event_type=HarnessEventType.GATE_EVALUATED,
                        run_id=state.run_spec.run_id,
                        step_id=step_id,
                        payload=result.to_dict(),
                    )
                )
        return results

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

    def _verify_gate_entries(
        self,
        state: HarnessState,
        step_id: str,
    ) -> tuple[tuple[str, DeterministicGate], ...]:
        entries: list[tuple[str, DeterministicGate]] = [
            (_gate_reference(gate), gate) for gate in self.verify_gates
        ]
        bindings = self._gate_bindings_by_run.get(state.run_spec.run_id, {}).get(
            step_id,
            (),
        )
        entries.extend((str(binding.reference), binding.gate) for binding in bindings)
        deduplicated: list[tuple[str, DeterministicGate]] = []
        seen: set[str] = set()
        for reference, gate in entries:
            if reference in seen:
                continue
            seen.add(reference)
            deduplicated.append((reference, gate))
        return tuple(deduplicated)

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

    def _worker_task(
        self,
        step_spec: HarnessStepSpec,
        state: HarnessState,
    ) -> dict[str, Any]:
        outputs = state.metadata.get("outputs", {})
        prior_outputs = outputs if isinstance(outputs, dict) else {}
        return {
            "run_id": state.run_spec.run_id,
            "step_id": step_spec.step_id,
            "worker_type": step_spec.worker_type.value,
            "inputs": {
                key: prior_outputs[key]
                if key in prior_outputs
                else state.run_spec.inputs.get(key)
                for key in step_spec.input_keys
            },
            "metadata": step_spec.metadata,
        }

    def _call_worker(
        self,
        step_spec: HarnessStepSpec,
        state: HarnessState,
        *,
        task: dict[str, Any] | None = None,
        activity: HarnessActivity | None = None,
        started_at=None,
    ) -> HarnessWorkerResult:
        task = dict(task or self._worker_task(step_spec, state))
        call_payload = dict(task)
        started_at = started_at or _next_transition_time(state)
        if activity is not None:
            call_payload.update(
                {
                    "activity_id": activity.activity_id,
                    "idempotency_key": activity.idempotency_key,
                    "activity_attempt": activity.attempt,
                    "activity_contract_version": activity.contract_version,
                }
            )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.WORKER_CALLED,
                run_id=state.run_spec.run_id,
                step_id=step_spec.step_id,
                payload=call_payload,
                occurred_at=started_at,
            )
        )
        execution_task = _task_with_activity(task, activity)
        binding = self._worker_bindings_by_run.get(
            state.run_spec.run_id,
            {},
        ).get(step_spec.step_id)
        if binding is None:
            raise HarnessValidationError(
                "exact worker binding is unavailable",
                code="unknown_runtime_worker_binding",
                details={
                    "code": "unknown_runtime_worker_binding",
                    "step_id": step_spec.step_id,
                    "worker_type": step_spec.worker_type.value,
                },
            )
        worker = binding.implementation
        if not callable(getattr(worker, "execute", None)):
            raise HarnessValidationError(
                "resolved worker binding does not expose execute(task)",
                code="invalid_runtime_contract_implementation",
                details={"reference": binding.reference.exact_ref},
            )
        return _coerce_worker_result(worker.execute(execution_task))

    def _quality_verdict(
        self,
        state: HarnessState,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
    ) -> HarnessQualityVerdict | None:
        step_spec = _get_step_spec(state, step_id)
        return aggregate_gate_verdict(
            gate_results,
            declared_gate_reference=step_spec.quality_gate,
        )

    def _recorded_quality_verdict(
        self,
        run_id: str,
        step_id: str,
    ) -> HarnessQualityVerdict | None:
        for event in reversed(self.event_port.read_history(run_id)):
            if (
                event.event_type != HarnessEventType.DECISION_RECORDED
                or event.step_id != step_id
                or not isinstance(event.deterministic_history, Mapping)
            ):
                continue
            handler_input = event.deterministic_history.get("handler_input")
            if not isinstance(handler_input, Mapping):
                continue
            verdict = handler_input.get("quality_verdict")
            if isinstance(verdict, Mapping):
                return HarnessQualityVerdict(**dict(verdict))
        return None

    def _recorded_gate_results_for_verify(
        self,
        state: HarnessState,
        step_id: str,
        transition: HarnessTransitionCommitted,
        *,
        worker_result: HarnessWorkerResult,
    ) -> tuple[HarnessGateResult, ...]:
        history = self.event_port.read_history(state.run_spec.run_id)
        try:
            transition_index = next(
                index
                for index, event in enumerate(history)
                if event.event_id == transition.transition_id
            )
        except StopIteration as exc:
            raise EventIncompleteHistoryError(
                "Harness history is missing its committed VERIFY transition"
            ) from exc

        recorded_events: list[HarnessEvent] = []
        found_verify_entry = False
        for event in reversed(history[:transition_index]):
            if event.event_type == HarnessEventType.TRANSITION_COMMITTED:
                if (
                    event.payload.get("transition_kind")
                    == HarnessTransitionKind.VERIFY_ENTRY.value
                ):
                    found_verify_entry = True
                break
            if (
                event.event_type == HarnessEventType.GATE_EVALUATED
                and event.step_id == step_id
            ):
                recorded_events.append(event)
        if not found_verify_entry:
            raise EventIncompleteHistoryError(
                "Harness committed VERIFY is missing its entry transition"
            )
        recorded_events.reverse()

        expected_references = tuple(
            reference for reference, _ in self._verify_gate_entries(state, step_id)
        )
        context = GateContext(
            state=state,
            step_spec=_get_step_spec(state, step_id),
            step_state=get_step_state(state, step_id),
            worker_result=worker_result,
            quality_verdict=None,
            budget=self._budget_snapshot(state, worker_result),
        )
        expected_input_refs = tuple(
            _gate_input_ref(context, reference) for reference in expected_references
        )
        if len(recorded_events) != len(expected_references):
            raise EventIncompleteHistoryError(
                "Harness committed VERIFY gate evidence count is incomplete"
            )
        return tuple(
            _gate_result_from_recorded_event(
                event,
                expected_reference=reference,
                expected_input_ref=expected_input_ref,
            )
            for event, reference, expected_input_ref in zip(
                recorded_events,
                expected_references,
                expected_input_refs,
                strict=True,
            )
        )

    def _recorded_verification_snapshot(
        self,
        state: HarnessState,
        step_id: str,
        *,
        evaluation_state: HarnessState,
        worker_result: HarnessWorkerResult,
    ) -> tuple[tuple[HarnessGateResult, ...], HarnessQualityVerdict] | None:
        expected_state_ref = HarnessStateProjection.from_state(state).checksum
        expected_references = tuple(
            reference
            for reference, _ in self._verify_gate_entries(evaluation_state, step_id)
        )
        context = GateContext(
            state=evaluation_state,
            step_spec=_get_step_spec(evaluation_state, step_id),
            step_state=get_step_state(evaluation_state, step_id),
            worker_result=worker_result,
            quality_verdict=None,
            budget=self._budget_snapshot(evaluation_state, worker_result),
        )
        expected_input_refs = tuple(
            _gate_input_ref(context, reference) for reference in expected_references
        )
        for event in reversed(self.event_port.read_history(state.run_spec.run_id)):
            if (
                event.event_type != HarnessEventType.DECISION_RECORDED
                or event.step_id != step_id
                or not isinstance(event.deterministic_history, Mapping)
            ):
                continue
            try:
                history = DeterministicHistoryRecord.from_dict(
                    event.deterministic_history
                )
                history.verify_integrity()
            except (TypeError, ValueError) as exc:
                raise EventStoreCorruptionError(
                    "Harness deterministic decision history is corrupt"
                ) from exc
            handler_input = history.handler_input
            if handler_input.get("before_state_checksum") != expected_state_ref:
                continue
            gate_values = handler_input.get("gate_results")
            verdict_value = handler_input.get("quality_verdict")
            if not isinstance(gate_values, tuple | list) or not isinstance(
                verdict_value,
                Mapping,
            ):
                continue
            if len(gate_values) != len(expected_references):
                raise EventStoreCorruptionError(
                    "recorded Harness gate evidence count conflicts with workflow binding"
                )
            gate_results: list[HarnessGateResult] = []
            for value, expected_reference, expected_input_ref in zip(
                gate_values,
                expected_references,
                expected_input_refs,
                strict=True,
            ):
                if not isinstance(value, Mapping):
                    raise EventStoreCorruptionError(
                        "recorded Harness gate evidence must be an object"
                    )
                reference = value.get("reference")
                input_ref = value.get("input_ref")
                result_ref = value.get("result_ref")
                reason_code = value.get("reason_code")
                passed = value.get("passed")
                score = value.get("score")
                if (
                    reference != expected_reference
                    or input_ref != expected_input_ref
                    or not _is_checksum_ref(result_ref)
                    or not isinstance(reason_code, str)
                    or not reason_code.strip()
                    or not isinstance(passed, bool)
                    or (
                        score is not None
                        and (
                            not isinstance(score, int | float)
                            or isinstance(score, bool)
                        )
                    )
                ):
                    raise EventStoreCorruptionError(
                        "recorded Harness gate evidence conflicts with exact binding"
                    )
                details: dict[str, Any] = {
                    "harness_gate": {
                        "reference": reference,
                        "input_ref": input_ref,
                        "result_ref": result_ref,
                        "reason_code": reason_code,
                    }
                }
                if score is not None:
                    details["score"] = float(score)
                gate_results.append(
                    HarnessGateResult(
                        gate_name=str(value.get("gate") or reference.rsplit("@", 1)[0]),
                        passed=passed,
                        details=details,
                    )
                )
            try:
                verdict = HarnessQualityVerdict(**dict(verdict_value))
            except (TypeError, ValueError, HarnessValidationError) as exc:
                raise EventStoreCorruptionError(
                    "recorded Harness quality verdict is invalid"
                ) from exc
            expected_verdict = aggregate_gate_verdict(
                gate_results,
                declared_gate_reference=_get_step_spec(state, step_id).quality_gate,
            )
            if expected_verdict is None or quality_verdict_evidence(
                verdict
            ) != quality_verdict_evidence(expected_verdict):
                raise EventStoreCorruptionError(
                    "recorded Harness quality verdict conflicts with gate evidence"
                )
            return tuple(gate_results), verdict
        return None

    def _record_decision(
        self,
        decision: HarnessDecision,
        *,
        decision_input: Mapping[str, Any],
        replay_activity: tuple[
            ReplayActivityDescriptor,
            PayloadReference,
        ]
        | None = None,
    ) -> None:
        ordinal = self._decision_indexes.get(decision.run_id, 0)
        history = harness_decision_history(
            workflow_id=str(decision_input["workflow_id"]),
            workflow_version=str(decision_input["workflow_version"]),
            command_ordinal=ordinal,
            decision_input=decision_input,
            decision=decision,
            causation_id=str(decision_input["causation_id"]),
            expected_activity=(None if replay_activity is None else replay_activity[0]),
            recorded_activity_ref=(
                None if replay_activity is None else replay_activity[1]
            ),
        )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.DECISION_RECORDED,
                run_id=decision.run_id,
                step_id=decision.step_id,
                payload=decision.to_dict(),
                occurred_at=decision.decided_at,
                deterministic_history=history.to_dict(),
            )
        )
        self._decision_indexes[decision.run_id] = ordinal + 1

    def _decision_input(
        self,
        state: HarnessState,
        *,
        gate_results: tuple[HarnessGateResult, ...],
        quality_verdict: HarnessQualityVerdict | None,
        expected_activity: ReplayActivityDescriptor | None,
        approval_outcome: str | None = None,
        side_effect_authorization: Mapping[str, Any] | None = None,
        side_effect_failure: Mapping[str, Any] | None = None,
        command_ordinal: int | None = None,
        causation_id: str | None = None,
    ) -> Mapping[str, Any]:
        run_id = state.run_spec.run_id
        ordinal = (
            self._decision_indexes.get(run_id, 0)
            if command_ordinal is None
            else command_ordinal
        )
        resolved_causation_id = causation_id or (
            self._committed_events[-1].event_id
            if self._committed_events
            else f"harness-run:{run_id}"
        )
        return harness_decision_input_snapshot(
            state=state,
            command_ordinal=ordinal,
            causation_id=str(resolved_causation_id),
            gate_results=gate_results,
            quality_verdict=quality_verdict,
            expected_activity=expected_activity,
            approval_outcome=approval_outcome,
            side_effect_authorization=side_effect_authorization,
            side_effect_failure=side_effect_failure,
            side_effect_state_refs=self._decision_side_effect_state_refs(state),
        )

    def _decision_side_effect_state_refs(
        self,
        state: HarnessState,
    ) -> Mapping[str, Any] | None:
        """Resolve successful worker-effect refs from the durable authority store.

        Safe transition projections intentionally omit raw side-effect metadata.
        Decision inputs still carry the bounded refs, so a restarted control
        plane must reconstruct them from the immutable decision/outcome pair
        before deriving the next terminal completion input.
        """

        step_id = state.current_step_id
        if step_id is None:
            return None
        step_state = get_step_state(state, step_id)
        if step_state.status is not HarnessStepStatus.SUCCEEDED:
            # A dangling COMPLETE_STEP decision is created before the step
            # becomes successful; including its store record would change the
            # original decision input during recovery.
            return None
        declared = self._side_effect_bindings_by_run.get(state.run_spec.run_id, {}).get(
            step_id
        )
        if declared is None:
            return None

        metadata = step_state.metadata
        refs = _canonical_side_effect_state_refs(metadata)
        if self.side_effect_store is None:
            return refs or None

        decisions = tuple(
            decision
            for decision in self.side_effect_store.list_decisions(
                run_id=state.run_spec.run_id
            )
            if decision.origin is HarnessSideEffectOrigin.WORKER
            and decision.step_id == step_id
            and decision.attempt == step_state.attempts
        )
        if len(decisions) > 1:
            raise EventStoreCorruptionError(
                "multiple worker side-effect decisions match one successful step attempt"
            )
        if not decisions:
            return refs or None
        decision = decisions[0]
        outcome = self.side_effect_store.get_outcome(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
            idempotency_key=decision.idempotency_key,
        )
        if outcome is None:
            raise EventIncompleteHistoryError(
                "successful side-effect step is missing its durable outcome"
            )
        durable_refs = _canonical_side_effect_state_refs(
            {
                "approval_evidence_ref": decision.approval_evidence_ref,
                "side_effect_effect_ref": checksum_for(decision.effect_id),
                "side_effect_intent_ref": decision.intent_ref,
                "side_effect_decision_ref": decision.checksum,
                "side_effect_outcome_ref": outcome.checksum,
                "side_effect_disposition": outcome.disposition.value,
            }
        )
        if any(durable_refs.get(key) != value for key, value in refs.items()):
            raise EventStoreCorruptionError(
                "successful step side-effect refs conflict with durable authority"
            )
        return durable_refs

    def _record_phase(
        self,
        state: HarnessState,
        phase: HarnessPhase,
        step_id: str,
        gate_results: tuple[HarnessGateResult, ...],
        *,
        boundary: HarnessPhaseBoundary,
    ) -> None:
        record = HarnessPhaseRecord(
            phase=phase,
            step_id=step_id,
            boundary=boundary,
            gate_results=tuple(result.to_dict() for result in gate_results),
            metadata={
                "turn_count": state.turn_count,
                "worker_call_count": state.worker_call_count,
            },
        )
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.PHASE_RECORDED,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                payload=record.to_dict(),
                occurred_at=record.occurred_at,
            )
        )

    def _record_state_change(
        self,
        previous: HarnessState,
        state: HarnessState,
        *,
        transition_kind: str,
    ) -> None:
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.RUN_STATE_CHANGED,
                run_id=state.run_spec.run_id,
                step_id=state.current_step_id,
                payload={"status": state.status.value},
                metadata={
                    "replan_count": state.replan_count,
                    "status_before": previous.status.value,
                    "status_after": state.status.value,
                    "transition_kind": transition_kind,
                    "turn_count": state.turn_count,
                    "worker_call_count": state.worker_call_count,
                },
                occurred_at=state.updated_at,
            )
        )

    def _record_step_change(
        self,
        previous: HarnessState,
        state: HarnessState,
        step_id: str,
        *,
        transition_kind: str,
    ) -> None:
        previous_step = get_step_state(previous, step_id)
        current_step = get_step_state(state, step_id)
        self._record_event(
            HarnessEvent(
                event_type=HarnessEventType.STEP_STATE_CHANGED,
                run_id=state.run_spec.run_id,
                step_id=step_id,
                payload=current_step.to_dict(),
                metadata={
                    "replan_count": state.replan_count,
                    "status_before": previous_step.status.value,
                    "status_after": current_step.status.value,
                    "transition_kind": transition_kind,
                    "turn_count": state.turn_count,
                    "worker_call_count": state.worker_call_count,
                },
                occurred_at=current_step.updated_at,
            )
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

    def _restore_recovery(self, run_spec: HarnessRunSpec) -> HarnessRecovery:
        self._prepare_run_spec(run_spec)
        self._recovered_gate_results = ()
        self._recovered_quality_verdict = None
        converged_exit_kind: HarnessTransitionKind | None = None
        converged_gate_results: tuple[HarnessGateResult, ...] = ()
        converged_quality_verdict: HarnessQualityVerdict | None = None
        while True:
            recovery = self.event_port.recover(run_spec)
            if not isinstance(recovery, HarnessRecovery):
                raise HarnessValidationError(
                    "Harness transition port returned an invalid recovery result"
                )
            self._state_versions[run_spec.run_id] = recovery.state_version
            self._recovered_worker_results = dict(recovery.worker_results)
            state = recovery.state
            if state is None or not recovery.transitions:
                break
            last_transition = recovery.transitions[-1]
            transition_kind = last_transition.transition_kind
            step_id = state.current_step_id

            if transition_kind == HarnessTransitionKind.EXECUTE_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery requires a current step"
                    )
                activity = _activity_for_state_step(state, step_id)
                if activity is None:
                    raise EventIncompleteHistoryError(
                        "Harness recovery is missing the worker activity descriptor"
                    )
                step_spec = _get_step_spec(state, step_id)
                worker_result = recovery.current_worker_result
                if worker_result is None:
                    task = self._worker_task(step_spec, state)
                    if checksum_for(task) != activity.input_checksum:
                        raise EventReplayMismatchError(
                            sequence=last_transition.stream_sequence
                            or last_transition.state_version,
                            reason=(
                                "Harness recovered activity input conflicts with "
                                "the committed activity descriptor"
                            ),
                        )
                    started_at = _next_transition_time(state)
                    worker_result = self.event_port.accept_activity(
                        activity,
                        task,
                        accepted_at=state.updated_at,
                        started_at=started_at,
                    )
                    if worker_result is None:
                        if activity.activity_id in recovery.called_activity_ids:
                            raise EventIncompleteHistoryError(
                                "Harness activity was dispatched without a durable result; "
                                "automatic worker re-execution is forbidden without "
                                "a verified idempotency capability"
                            )
                        worker_result = self._call_worker(
                            step_spec,
                            state,
                            task=task,
                            activity=activity,
                            started_at=started_at,
                        )
                    else:
                        worker_result = _coerce_worker_result(worker_result)
                    activity_result_event_id = self._record_activity_result(
                        state,
                        step_id=step_id,
                        activity=activity,
                        worker_result=worker_result,
                    )
                else:
                    activity_result_event_id = activity.result_event_id
                state = self._commit_worker_result_transition(
                    state,
                    step_id=step_id,
                    step_spec=step_spec,
                    worker_result=worker_result,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                self._commit_execute_exit_transition(
                    state,
                    step_id=step_id,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                continue

            if transition_kind == HarnessTransitionKind.WORKER_RESULT_COMMITTED:
                if step_id is None or recovery.current_worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery is missing its committed worker result"
                    )
                activity = _activity_for_state_step(state, step_id)
                activity_result_event_id = _activity_result_event_id(state, step_id)
                if activity is None or activity_result_event_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness execute recovery is missing its activity references"
                    )
                self._commit_execute_exit_transition(
                    state,
                    step_id=step_id,
                    activity=activity,
                    activity_result_event_id=activity_result_event_id,
                    decision=None,
                )
                continue

            if transition_kind == HarnessTransitionKind.PLAN_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness plan recovery requires a current step"
                    )
                gate_results = self._evaluate_gates(
                    self.plan_gates,
                    state,
                    step_id,
                    worker_result=None,
                    quality_verdict=None,
                    record_events=False,
                )
                self._commit_plan_exit(
                    state,
                    step_id=step_id,
                    gate_results=gate_results,
                    record_observations=False,
                )
                converged_exit_kind = HarnessTransitionKind.PLAN_EXIT
                converged_gate_results = gate_results
                continue

            if transition_kind == HarnessTransitionKind.VERIFY_ENTRY:
                worker_result = recovery.current_worker_result
                if step_id is None or worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness verify recovery requires a committed worker result"
                    )
                gate_entries = self._verify_gate_entries(state, step_id)
                gate_results = self._evaluate_gates(
                    tuple(gate for _, gate in gate_entries),
                    state,
                    step_id,
                    worker_result=worker_result,
                    quality_verdict=None,
                    record_events=False,
                    gate_references=tuple(reference for reference, _ in gate_entries),
                )
                quality_verdict = self._quality_verdict(state, step_id, gate_results)
                self._commit_verify_exit(
                    state,
                    step_id=step_id,
                    gate_results=gate_results,
                    quality_verdict=quality_verdict,
                    record_observations=False,
                )
                converged_exit_kind = HarnessTransitionKind.VERIFY_EXIT
                converged_gate_results = gate_results
                converged_quality_verdict = quality_verdict
                continue

            if transition_kind == HarnessTransitionKind.REPLAN_ENTRY:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness replan recovery requires a current step"
                    )
                self._commit_replan_exit(
                    state,
                    step_id=step_id,
                    record_observations=False,
                )
                continue
            break

        if recovery.state is not None and recovery.transitions:
            state = recovery.state
            last_transition = recovery.transitions[-1]
            step_id = state.current_step_id
            if last_transition.transition_kind == HarnessTransitionKind.PLAN_EXIT:
                if step_id is None:
                    raise EventIncompleteHistoryError(
                        "Harness plan recovery requires a current step"
                    )
                if converged_exit_kind == HarnessTransitionKind.PLAN_EXIT:
                    gate_results = converged_gate_results
                else:
                    evaluation_state = _phase_entry_evaluation_state(
                        recovery,
                        expected_entry=HarnessTransitionKind.PLAN_ENTRY,
                    )
                    gate_results = self._evaluate_gates(
                        self.plan_gates,
                        evaluation_state,
                        step_id,
                        worker_result=None,
                        quality_verdict=None,
                        record_events=False,
                    )
                _validate_recovered_gate_results(last_transition, gate_results)
                self._recovered_gate_results = gate_results
            elif last_transition.transition_kind == HarnessTransitionKind.VERIFY_EXIT:
                worker_result = recovery.current_worker_result
                if step_id is None or worker_result is None:
                    raise EventIncompleteHistoryError(
                        "Harness verify recovery requires a committed worker result"
                    )
                evaluation_state = _phase_entry_evaluation_state(
                    recovery,
                    expected_entry=HarnessTransitionKind.VERIFY_ENTRY,
                )
                recorded_verification = self._recorded_verification_snapshot(
                    state,
                    step_id,
                    evaluation_state=evaluation_state,
                    worker_result=worker_result,
                )
                if recorded_verification is not None:
                    gate_results, quality_verdict = recorded_verification
                elif converged_exit_kind == HarnessTransitionKind.VERIFY_EXIT:
                    gate_results = converged_gate_results
                    quality_verdict = converged_quality_verdict
                else:
                    gate_results = self._recorded_gate_results_for_verify(
                        evaluation_state,
                        step_id,
                        last_transition,
                        worker_result=worker_result,
                    )
                    quality_verdict = self._quality_verdict(
                        evaluation_state,
                        step_id,
                        gate_results,
                    )
                _validate_recovered_gate_results(
                    last_transition,
                    gate_results,
                    quality_verdict=quality_verdict,
                )
                self._recovered_gate_results = gate_results
                self._recovered_quality_verdict = quality_verdict
            elif last_transition.transition_kind == HarnessTransitionKind.STEP_SUCCESS:
                if step_id is not None:
                    self._recovered_quality_verdict = self._recorded_quality_verdict(
                        run_spec.run_id,
                        step_id,
                    )
        history = self.event_port.read_history(run_spec.run_id)
        if not isinstance(history, tuple) or not all(
            isinstance(event, HarnessEvent) for event in history
        ):
            raise HarnessValidationError(
                "Harness transition port returned an invalid history projection"
            )
        self._committed_events = list(history)
        self._decision_indexes[run_spec.run_id] = sum(
            1 for event in history if _is_scheduler_decision_event(event)
        )
        pending_completion = _pending_completion_from_history(history)
        if pending_completion is None:
            self._pending_completion_decisions.pop(run_spec.run_id, None)
        else:
            self._pending_completion_decisions[run_spec.run_id] = pending_completion
        return recovery

    def _commit_transition(
        self,
        previous: HarnessState | None,
        state: HarnessState,
        *,
        transition_kind: HarnessTransitionKind | str,
        occurred_at=None,
        decision: HarnessDecision | None = None,
        gate_results: tuple[HarnessGateResult, ...] = (),
        quality_verdict: HarnessQualityVerdict | None = None,
        activity: HarnessActivity | None = None,
        activity_result_event_id: str | None = None,
    ) -> HarnessState:
        run_id = state.run_spec.run_id
        from_version = self._state_versions.get(run_id, 0)
        transition_time = occurred_at or state.updated_at
        is_verify_exit = str(transition_kind) == HarnessTransitionKind.VERIFY_EXIT.value
        commit = self.event_port.commit_transition(
            previous,
            state,
            from_version=from_version,
            transition_kind=transition_kind,
            occurred_at=transition_time,
            decision=(
                None if decision is None else _decision_transition_projection(decision)
            ),
            gate_results=(
                verification_evidence(gate_results, quality_verdict)
                if is_verify_exit
                else tuple(result.to_dict() for result in gate_results)
            ),
            budget=self._budget_snapshot(state, None).to_dict(),
            activity=activity,
            activity_result_event_id=activity_result_event_id,
        )
        if not isinstance(commit, HarnessTransitionCommit):
            raise HarnessValidationError(
                "Harness transition port returned an invalid commit result"
            )
        if commit.transition.from_version != from_version:
            raise HarnessValidationError(
                "Harness transition port returned a conflicting state version"
            )
        self._state_versions[run_id] = commit.transition.state_version
        projected = HarnessEvent(
            event_id=commit.transition.transition_id,
            event_type=HarnessEventType.TRANSITION_COMMITTED,
            run_id=run_id,
            step_id=state.current_step_id,
            payload=commit.transition.to_payload(),
            occurred_at=commit.transition.occurred_at,
        )
        if not any(
            event.event_id == projected.event_id for event in self._committed_events
        ):
            self._committed_events.append(projected)
        return commit.state

    def _result(
        self,
        state: HarnessState,
        *,
        decisions: list[HarnessDecision],
        worker_results: dict[str, HarnessWorkerResult] | None = None,
        quality_verdicts: dict[str, HarnessQualityVerdict] | None = None,
    ) -> HarnessRunResult:
        run_id = state.run_spec.run_id
        all_worker_results = {
            **self._recovered_worker_results,
            **(worker_results or {}),
        }
        return HarnessRunResult(
            state=state,
            decisions=tuple(decisions),
            events=tuple(
                event for event in self._committed_events if event.run_id == run_id
            ),
            worker_results={
                key: value for key, value in all_worker_results.items() if key
            },
            quality_verdicts={
                key: value for key, value in (quality_verdicts or {}).items() if key
            },
            side_effect_outcomes=dict(self._side_effect_outcomes.get(run_id, {})),
        )


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


def _side_effect_authorization_projection(
    authorization: HarnessSideEffectDecision,
) -> dict[str, Any]:
    # Keep only the refs needed to identify and scope the authorization.  The
    # complete decision (including atomic-group and persisted attempt ledger)
    # is recoverable from the side-effect store through ``decision_ref``;
    # duplicating those long checksums in every deterministic history record
    # can exceed the canonical event extension budget.
    return {
        "origin": authorization.origin.value,
        "effect_ref": checksum_for(authorization.effect_id),
        "intent_ref": authorization.intent_ref,
        "identity_scope_ref": authorization.identity_scope_ref,
        "subject_scope_ref": authorization.subject_scope_ref,
        "approval_evidence_ref": authorization.approval_evidence_ref,
        "decision_ref": authorization.checksum,
        "disposition": authorization.disposition.value,
        "idempotency_ref": checksum_for(authorization.idempotency_key),
    }


def _canonical_side_effect_state_refs(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in _SIDE_EFFECT_STATE_REF_KEYS
        if value.get(key) is not None
    }


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


def _is_scheduler_decision_event(event: HarnessEvent) -> bool:
    if event.event_type is not HarnessEventType.DECISION_RECORDED:
        return False
    if event.metadata.get("projection_kind") in {
        "side_effect_authorization",
        "side_effect_outcome",
    }:
        return False
    history = event.deterministic_history
    if isinstance(history, Mapping):
        commands = history.get("commands")
        if isinstance(commands, list | tuple):
            return bool(commands)
    return True


def _pending_completion_from_history(
    history: tuple[HarnessEvent, ...],
) -> _PendingCompletionDecision | None:
    last_transition_index = -1
    for index, event in enumerate(history):
        if event.event_type is HarnessEventType.TRANSITION_COMMITTED:
            last_transition_index = index
    candidates: list[_PendingCompletionDecision] = []
    for index, event in enumerate(
        history[last_transition_index + 1 :],
        start=last_transition_index + 1,
    ):
        if not _is_scheduler_decision_event(event):
            continue
        payload = event.payload
        raw_decision_payload = payload.get("payload")
        authorization = None
        if isinstance(raw_decision_payload, Mapping):
            authorization = raw_decision_payload.get("side_effect_authorization")
        safe_decision_payload = payload.get("decision_payload")
        if authorization is None and isinstance(safe_decision_payload, Mapping):
            authorization = safe_decision_payload.get("side_effect_authorization")
        history_value = event.deterministic_history
        handler_input = (
            history_value.get("handler_input")
            if isinstance(history_value, Mapping)
            else None
        )
        current_policy = (
            handler_input.get("current_step_policy")
            if isinstance(handler_input, Mapping)
            else None
        )
        if authorization is None and isinstance(current_policy, Mapping):
            authorization = current_policy.get("side_effect_authorization")
        if authorization is None:
            continue
        if not isinstance(authorization, Mapping) or not isinstance(
            handler_input, Mapping
        ):
            raise EventStoreCorruptionError(
                "dangling side-effect decision evidence is incomplete"
            )
        try:
            decision_type = HarnessDecisionType(payload.get("decision_type"))
            command_ordinal = int(handler_input["command_ordinal"])
            causation_id = str(handler_input["causation_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EventStoreCorruptionError(
                "dangling side-effect decision identity is invalid"
            ) from exc
        if decision_type not in {
            HarnessDecisionType.COMPLETE_STEP,
            HarnessDecisionType.COMPLETE_RUN,
        }:
            raise EventStoreCorruptionError(
                "side-effect authorization is attached to a non-completion decision"
            )
        candidates.append(
            _PendingCompletionDecision(
                decision_type=decision_type,
                step_id=event.step_id,
                authorization_projection=dict(authorization),
                command_ordinal=command_ordinal,
                causation_id=causation_id,
                decided_at=event.occurred_at,
                history_cutoff_id=(None if index == 0 else history[index - 1].event_id),
            )
        )
    if len(candidates) > 1:
        raise EventStoreCorruptionError(
            "multiple dangling side-effect completion decisions are ambiguous"
        )
    return None if not candidates else candidates[0]


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
        }
    )


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
    if not isinstance(payload, Mapping):
        raise HarnessValidationError(
            "worker must return a HarnessWorkerResult-compatible object"
        )
    try:
        return HarnessWorkerResult(
            status=payload.get("status"),
            output=payload.get("output", {}),
            artifacts=payload.get("artifacts", ()),
            diagnostics=payload.get("diagnostics", {}),
            metrics=payload.get("metrics", {}),
            error=payload.get("error"),
            effect_intent=payload.get("effect_intent"),
        )
    except (TypeError, ValueError, HarnessValidationError) as exc:
        if isinstance(exc, HarnessValidationError):
            raise
        raise HarnessValidationError(
            "worker returned an invalid result contract"
        ) from exc


def _is_checksum_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def _gate_result_from_recorded_event(
    event: HarnessEvent,
    *,
    expected_reference: str,
    expected_input_ref: str,
) -> HarnessGateResult:
    payload = event.payload
    details = payload.get("details")
    if isinstance(details, Mapping) and isinstance(
        details.get("harness_gate"), Mapping
    ):
        result = HarnessGateResult(
            gate_name=str(payload.get("gate") or ""),
            passed=payload.get("passed"),
            reason=None if payload.get("reason") is None else str(payload["reason"]),
            details=dict(details),
        )
    else:
        reference = payload.get("reference")
        input_ref = payload.get("input_ref")
        result_ref = payload.get("result_ref")
        reason_code = payload.get("reason_code")
        score = payload.get("score")
        if (
            not isinstance(reference, str)
            or not _is_checksum_ref(input_ref)
            or not _is_checksum_ref(result_ref)
            or not isinstance(reason_code, str)
            or not reason_code.strip()
            or not isinstance(payload.get("passed"), bool)
            or (
                score is not None
                and (not isinstance(score, int | float) or isinstance(score, bool))
            )
        ):
            raise EventIncompleteHistoryError(
                "Harness committed VERIFY is missing versioned gate evidence"
            )
        safe_details: dict[str, Any] = {
            "harness_gate": {
                "reference": reference,
                "input_ref": input_ref,
                "result_ref": result_ref,
                "reason_code": reason_code,
            }
        }
        if score is not None:
            safe_details["score"] = float(score)
        result = HarnessGateResult(
            gate_name=str(payload.get("gate") or ""),
            passed=payload["passed"],
            details=safe_details,
        )
    try:
        evidence = gate_result_evidence(result)
    except (TypeError, ValueError, HarnessValidationError) as exc:
        raise EventStoreCorruptionError(
            "recorded Harness gate evidence is invalid"
        ) from exc
    expected_gate_id = expected_reference.rsplit("@", maxsplit=1)[0]
    if (
        evidence["reference"] != expected_reference
        or evidence["gate"] != expected_gate_id
        or evidence["input_ref"] != expected_input_ref
        or not _is_checksum_ref(evidence["result_ref"])
    ):
        raise EventStoreCorruptionError(
            "recorded Harness gate evidence conflicts with the exact binding"
        )
    return result


def _require_step(decision: HarnessDecision) -> str:
    if decision.step_id:
        return decision.step_id
    if decision.target_step_id:
        return decision.target_step_id
    raise ValueError("decision requires a step_id")


def _is_transition_port(value: Any) -> bool:
    return all(
        callable(getattr(value, method_name, None))
        for method_name in (
            "record",
            "create_activity",
            "commit_transition",
            "recover",
            "read_history",
            "require_activity_storage",
            "accept_activity",
            "resolve_replay_activity",
            "record_activity_result",
        )
    )


def _resolve_replay_activity_binding(
    event_port: Any,
    state: HarnessState,
) -> tuple[ReplayActivityDescriptor, PayloadReference] | None:
    binding = event_port.resolve_replay_activity(state)
    if binding is None:
        return None
    if (
        not isinstance(binding, tuple)
        or len(binding) != 2
        or not isinstance(binding[0], ReplayActivityDescriptor)
        or not isinstance(binding[1], PayloadReference)
    ):
        raise HarnessValidationError(
            "Harness transition port returned an invalid replay activity binding"
        )
    return binding


def _get_step_spec(state: HarnessState, step_id: str) -> HarnessStepSpec:
    for step in state.run_spec.workflow.steps:
        if step.step_id == step_id:
            return step
    raise LookupError(step_id)


def _halt_current_step(
    state: HarnessState,
    step_id: str,
    reason: str | None,
    *,
    at,
) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.HALTED:
        return state
    if step_state.status in {
        HarnessStepStatus.SUCCEEDED,
        HarnessStepStatus.FAILED,
        HarnessStepStatus.SKIPPED,
    }:
        return state
    return transition_step(
        state,
        step_id,
        HarnessStepStatus.HALTED,
        error=reason,
        current_step_id=step_id,
        at=at,
    )


def _fail_current_step(
    state: HarnessState,
    step_id: str,
    reason: str | None,
    *,
    at,
) -> HarnessState:
    step_state = get_step_state(state, step_id)
    if step_state.status == HarnessStepStatus.FAILED:
        return state
    if step_state.status in {
        HarnessStepStatus.SUCCEEDED,
        HarnessStepStatus.SKIPPED,
        HarnessStepStatus.HALTED,
    }:
        return state
    return transition_step(
        state,
        step_id,
        HarnessStepStatus.FAILED,
        error=reason,
        current_step_id=step_id,
        at=at,
    )


def _merge_outputs(
    state: HarnessState,
    step_id: str,
    worker_result: HarnessWorkerResult | None,
) -> HarnessState:
    if worker_result is None:
        return state
    step_spec = _get_step_spec(state, step_id)
    outputs = (
        dict(state.metadata.get("outputs", {}))
        if isinstance(state.metadata.get("outputs", {}), dict)
        else {}
    )
    if step_spec.output_key:
        outputs[step_spec.output_key] = worker_result.output
    plan_keys = set(state.metadata.get("plan_keys", ()))
    if "plan_key" in worker_result.output:
        plan_keys.add(str(worker_result.output["plan_key"]))
    claims = set(state.metadata.get("claims", ()))
    claims.update(_coerce_output_sequence(worker_result.output.get("claims", ())))
    questions = set(state.metadata.get("questions", ()))
    questions.update(_coerce_output_sequence(worker_result.output.get("questions", ())))
    evolution_usage = _evolution_usage(state, worker_result)
    return replace(
        state,
        metadata={
            **state.metadata,
            "outputs": outputs,
            "plan_keys": tuple(sorted(plan_keys)),
            "claims": tuple(sorted(claims)),
            "questions": tuple(sorted(questions)),
            **evolution_usage,
        },
    )


def _evolution_usage(
    state: HarnessState, worker_result: HarnessWorkerResult
) -> dict[str, int]:
    output = worker_result.output
    return {
        "evolution_epochs_used": int(state.metadata.get("evolution_epochs_used", 0))
        + int(output.get("evolution_epochs", 0)),
        "candidates_used": int(state.metadata.get("candidates_used", 0))
        + int(output.get("candidate_count", 0)),
        "patch_operations_used": int(state.metadata.get("patch_operations_used", 0))
        + int(output.get("patch_operations", 0)),
        "eval_cases_used": int(state.metadata.get("eval_cases_used", 0))
        + int(output.get("eval_cases", 0)),
        "sandbox_runs_used": int(state.metadata.get("sandbox_runs_used", 0))
        + int(output.get("sandbox_runs", 0)),
    }


def _run_loop_stop_statuses() -> frozenset[HarnessRunStatus]:
    return terminal_run_statuses().union(
        {HarnessRunStatus.WAITING_APPROVAL, HarnessRunStatus.BLOCKED}
    )


def _coerce_output_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(str(item) for item in value)
    return (str(value),)


def _next_transition_time(state: HarnessState):
    return state.updated_at + timedelta(microseconds=1)


def _decision_transition_projection(decision: HarnessDecision) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "decision_type": decision.decision_type.value,
        "step_id": decision.step_id,
        "target_step_id": decision.target_step_id,
        "payload_ref": checksum_for(decision.payload),
    }
    if decision.reason is not None:
        projection["reason_ref"] = checksum_for(decision.reason)
    budget_exhausted = decision.payload.get("budget_exhausted")
    if budget_exhausted is not None:
        projection["budget_exhausted"] = str(budget_exhausted)
    return projection


def _activity_for_state_step(
    state: HarnessState,
    step_id: str,
) -> HarnessActivity | None:
    step = get_step_state(state, step_id)
    metadata = step.metadata
    activity_id = metadata.get("activity_id")
    if activity_id is None:
        return None
    step_spec = _get_step_spec(state, step_id)
    try:
        return HarnessActivity(
            activity_id=str(activity_id),
            run_id=state.run_spec.run_id,
            step_id=step_id,
            attempt=int(metadata.get("activity_attempt", step.attempts)),
            activity_type=str(
                metadata.get("activity_type", step_spec.worker_type.value)
            ),
            contract_version=str(metadata.get("activity_contract_version")),
            idempotency_key=str(metadata.get("activity_idempotency_key")),
            input_checksum=str(metadata.get("activity_input_checksum")),
            identity_scope_ref=(
                None
                if metadata.get("activity_identity_scope_ref") is None
                else str(metadata["activity_identity_scope_ref"])
            ),
            worker_version=str(metadata.get("activity_worker_version")),
        )
    except (TypeError, ValueError, HarnessValidationError) as exc:
        raise EventIncompleteHistoryError(
            "Harness state contains an incomplete activity descriptor"
        ) from exc


def _activity_result_event_id(state: HarnessState, step_id: str) -> str | None:
    value = get_step_state(state, step_id).metadata.get("activity_result_event_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _in_memory_called_activity_ids(
    *,
    state: HarnessState | None,
    transitions: tuple[HarnessTransitionCommitted, ...],
    events: tuple[HarnessEvent, ...],
) -> frozenset[str]:
    if (
        state is None
        or not transitions
        or transitions[-1].transition_kind != HarnessTransitionKind.EXECUTE_ENTRY
        or state.current_step_id is None
    ):
        return frozenset()
    activity = _activity_for_state_step(state, state.current_step_id)
    if activity is None:
        return frozenset()
    transition_id = transitions[-1].transition_id
    try:
        transition_index = next(
            index
            for index, event in enumerate(events)
            if event.event_id == transition_id
        )
    except StopIteration as exc:
        raise EventStoreCorruptionError(
            "Harness in-memory history is missing its execute entry"
        ) from exc
    markers = tuple(
        event
        for event in events[transition_index + 1 :]
        if event.event_type == HarnessEventType.WORKER_CALLED
    )
    if not markers:
        return frozenset()
    if len(markers) != 1:
        raise EventStoreCorruptionError(
            "Harness execute entry has duplicate worker call markers"
        )
    marker = markers[0]
    if marker.run_id != state.run_spec.run_id or marker.step_id != activity.step_id:
        raise EventStoreCorruptionError(
            "Harness worker call marker context conflicts with activity"
        )
    validate_activity_call_marker(
        marker.payload,
        expected_activity=activity,
    )
    return frozenset({activity.activity_id})


def _validate_recovered_gate_results(
    transition: HarnessTransitionCommitted,
    gate_results: tuple[HarnessGateResult, ...],
    *,
    quality_verdict: HarnessQualityVerdict | None = None,
) -> None:
    evidence: Any
    if transition.transition_kind == HarnessTransitionKind.VERIFY_EXIT:
        evidence = verification_evidence(gate_results, quality_verdict)
    else:
        evidence = tuple(result.to_dict() for result in gate_results)
    gate_ref = checksum_for(evidence)
    if transition.gate_ref != gate_ref:
        raise EventReplayMismatchError(
            sequence=transition.stream_sequence or transition.state_version,
            reason="Harness deterministic gate result conflicts with durable history",
        )


def _phase_entry_evaluation_state(
    recovery: HarnessRecovery,
    *,
    expected_entry: HarnessTransitionKind,
) -> HarnessState:
    if recovery.state is None or len(recovery.transitions) < 2:
        raise EventIncompleteHistoryError(
            "Harness phase exit is missing its committed entry transition"
        )
    entry = recovery.transitions[-2]
    if entry.transition_kind != expected_entry:
        raise EventIncompleteHistoryError(
            "Harness phase exit does not follow its committed entry transition"
        )
    entry_state = entry.state.restore(recovery.state.run_spec)
    hydrated_steps = {step.step_id: step for step in recovery.state.step_states}
    return replace(
        entry_state,
        step_states=tuple(
            replace(
                step,
                metadata=hydrated_steps[step.step_id].metadata,
            )
            for step in entry_state.step_states
        ),
        metadata=recovery.state.metadata,
    )


def _terminal_transition_kind(
    status: HarnessRunStatus,
    decision: HarnessDecision,
) -> HarnessTransitionKind:
    if status == HarnessRunStatus.SUCCEEDED:
        return HarnessTransitionKind.SUCCESS
    if status == HarnessRunStatus.FAILED:
        return HarnessTransitionKind.FAILURE
    if status == HarnessRunStatus.CANCELLED:
        return HarnessTransitionKind.CANCEL
    if status == HarnessRunStatus.BLOCKED:
        return HarnessTransitionKind.WAIT
    if (
        status == HarnessRunStatus.HALTED
        and decision.payload.get("budget_exhausted") is not None
    ):
        return HarnessTransitionKind.BUDGET_EXHAUSTION
    return HarnessTransitionKind.HALT


__all__ = ["HarnessControlPlane", "HarnessRunResult", "InMemoryHarnessEventPort"]
