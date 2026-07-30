from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessCompensationStatus,
    HarnessEvidenceKind,
    HarnessGraphReference,
    HarnessGraphState,
    HarnessJoinKind,
    HarnessJoinStatus,
    HarnessLoopIteration,
    HarnessLoopCounterState,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
    HarnessWaitStatus,
    RunLifecycle,
)
from framework.harness.workflow.canonical import (
    canonical_checksum,
    freeze_json,
    required_text,
    thaw_json,
)
from framework.harness.workflow.conditions import evaluate_condition
from framework.harness.workflow.graph import (
    HarnessControlNode,
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphEdge,
    HarnessGraphEdgeKind,
    HarnessExecutableNode,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.versioning import HARNESS_GRAPH_EVALUATOR_VERSION


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_SUCCESSFUL_NODE_STATUSES = frozenset(
    {
        HarnessNodeInstanceStatus.SUCCEEDED,
        HarnessNodeInstanceStatus.COMPENSATED,
    }
)
_FORWARD_DEPENDENCY_EDGE_KINDS = frozenset(
    {
        HarnessGraphEdgeKind.DEPENDENCY,
        HarnessGraphEdgeKind.WAIT_RESUME,
        HarnessGraphEdgeKind.WAIT_TIMEOUT,
    }
)


class HarnessGraphCandidateType(StrEnum):
    ACTIVATE_NODE = "activate_node"
    COMPLETE_CONTROL_NODE = "complete_control_node"
    SELECT_CHOICE = "select_choice"
    OPEN_FORK = "open_fork"
    SATISFY_JOIN = "satisfy_join"
    FAIL_JOIN = "fail_join"
    SELECT_PARALLEL_WINNER = "select_parallel_winner"
    START_LOOP_ITERATION = "start_loop_iteration"
    EXIT_LOOP = "exit_loop"
    EXHAUST_LOOP = "exhaust_loop"
    REGISTER_WAIT = "register_wait"
    RESUME_WAIT = "resume_wait"
    APPLY_MERGE = "apply_merge"
    SCHEDULE_COMPENSATION = "schedule_compensation"
    PROJECT_RUN_WAITING = "project_run_waiting"
    COMPLETE_RUN = "complete_run"
    HALT_RUN = "halt_run"


class HarnessGraphObservationType(StrEnum):
    VERIFIED_OUTPUT = "verified_output"
    WORKER_STATUS = "worker_status"
    QUALITY_VERDICT = "quality_verdict"
    GATE_RESULT = "gate_result"


@dataclass(frozen=True, slots=True)
class HarnessAcceptedGraphObservation:
    observation_type: HarnessGraphObservationType | str
    node_id: str
    node_instance_id: str
    attempt: int
    event_sequence: int
    contract_ref: HarnessContractReference
    evidence_ref: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    control_fact_paths: tuple[str, ...] = ()
    payload_ref: str = field(init=False)
    observation_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        observation_type = HarnessGraphObservationType(self.observation_type)
        node_id = required_text(self.node_id, "graph_observation.node_id")
        node_instance_id = required_text(
            self.node_instance_id,
            "graph_observation.node_instance_id",
        )
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
        ):
            raise HarnessValidationError(
                "graph observation attempt must be positive",
                code="invalid_graph_observation_attempt",
            )
        if (
            not isinstance(self.event_sequence, int)
            or isinstance(self.event_sequence, bool)
            or self.event_sequence < 1
        ):
            raise HarnessValidationError(
                "graph observation event sequence must be positive",
                code="invalid_graph_observation_sequence",
            )
        if not isinstance(self.contract_ref, HarnessContractReference):
            raise TypeError(
                "graph observation contract_ref must be HarnessContractReference"
            )
        evidence_ref = _checksum(
            self.evidence_ref,
            "graph_observation.evidence_ref",
        )
        payload = freeze_json(self.payload, "graph_observation.payload")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "graph observation payload must be an object",
                code="invalid_graph_observation_payload",
            )
        control_fact_paths = _control_fact_paths(self.control_fact_paths)
        if observation_type is HarnessGraphObservationType.VERIFIED_OUTPUT:
            if self.contract_ref.contract_kind is not HarnessContractKind.STEP:
                raise HarnessValidationError(
                    "verified output observation requires an exact Step reference",
                    code="graph_observation_contract_mismatch",
                )
            projected_payload = _project_control_fact_payload(
                thaw_json(payload),
                control_fact_paths,
            )
            if projected_payload != thaw_json(payload):
                raise HarnessValidationError(
                    "verified output observation contains undeclared control data",
                    code="undeclared_graph_control_fact",
                )
            payload = freeze_json(projected_payload, "graph_observation.payload")
        elif observation_type is HarnessGraphObservationType.WORKER_STATUS:
            if self.contract_ref.contract_kind is not HarnessContractKind.WORKER:
                raise HarnessValidationError(
                    "worker status observation requires an exact Worker reference",
                    code="graph_observation_contract_mismatch",
                )
            _validate_status_payload(payload)
        elif observation_type is HarnessGraphObservationType.QUALITY_VERDICT:
            if self.contract_ref.contract_kind is not HarnessContractKind.GATE:
                raise HarnessValidationError(
                    "quality verdict observation requires an exact Gate reference",
                    code="graph_observation_contract_mismatch",
                )
            _validate_quality_payload(payload)
        elif observation_type is HarnessGraphObservationType.GATE_RESULT:
            if self.contract_ref.contract_kind is not HarnessContractKind.GATE:
                raise HarnessValidationError(
                    "Gate result observation requires an exact Gate reference",
                    code="graph_observation_contract_mismatch",
                )
            _validate_gate_payload(payload)
        if (
            observation_type is not HarnessGraphObservationType.VERIFIED_OUTPUT
            and control_fact_paths
        ):
            raise HarnessValidationError(
                "only verified output observations may declare control facts",
                code="graph_observation_control_fact_mismatch",
            )
        object.__setattr__(self, "observation_type", observation_type)
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "evidence_ref", evidence_ref)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "control_fact_paths", control_fact_paths)
        object.__setattr__(
            self,
            "payload_ref",
            canonical_checksum(thaw_json(payload)),
        )
        object.__setattr__(
            self,
            "observation_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "observation_type": self.observation_type.value,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "event_sequence": self.event_sequence,
            "contract_ref": self.contract_ref.to_dict(),
            "evidence_ref": self.evidence_ref,
            "payload": thaw_json(self.payload),
            "control_fact_paths": list(self.control_fact_paths),
            "payload_ref": self.payload_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "observation_checksum": self.observation_checksum,
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphEvaluationContext:
    inputs: Mapping[str, Any] = field(default_factory=dict)
    observations: tuple[HarnessAcceptedGraphObservation, ...] = ()

    def __post_init__(self) -> None:
        inputs = freeze_json(self.inputs, "graph_context.inputs")
        if not isinstance(inputs, Mapping):
            raise HarnessValidationError(
                "graph evaluation context inputs must be an object",
                code="invalid_graph_evaluation_context",
            )
        observations = tuple(self.observations)
        if not all(
            isinstance(item, HarnessAcceptedGraphObservation) for item in observations
        ):
            raise TypeError(
                "graph evaluation observations must contain HarnessAcceptedGraphObservation values"
            )
        observations = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.event_sequence,
                    item.node_instance_id,
                    item.attempt,
                    item.observation_type.value,
                    item.contract_ref.exact_ref,
                    item.observation_checksum,
                ),
            )
        )
        if len(observations) != len(
            {item.observation_checksum for item in observations}
        ):
            raise HarnessValidationError(
                "graph observations must have unique checksums",
                code="duplicate_graph_observation",
            )
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "observations", observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inputs": thaw_json(self.inputs),
            "observations": [item.to_dict() for item in self.observations],
        }

    @property
    def checksum(self) -> str:
        return canonical_checksum(self.to_dict())

    def for_node_instance(
        self,
        node_instance_id: str,
    ) -> tuple[HarnessAcceptedGraphObservation, ...]:
        return tuple(
            item
            for item in self.observations
            if item.node_instance_id == node_instance_id
        )


@dataclass(frozen=True, slots=True)
class HarnessGraphCandidate:
    candidate_type: HarnessGraphCandidateType | str
    reason_code: str
    priority: int
    node_id: str | None = None
    node_instance_id: str | None = None
    target_node_ids: tuple[str, ...] = ()
    branch_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    candidate_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        candidate_type = HarnessGraphCandidateType(self.candidate_type)
        reason_code = required_text(self.reason_code, "graph_candidate.reason_code")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise HarnessValidationError(
                "graph candidate priority must be an integer",
                code="invalid_graph_candidate_priority",
            )
        node_id = _optional_text(self.node_id, "graph_candidate.node_id")
        node_instance_id = _optional_text(
            self.node_instance_id,
            "graph_candidate.node_instance_id",
        )
        target_node_ids = _ordered_unique_text_tuple(
            self.target_node_ids,
            "graph_candidate.target_node_ids",
        )
        branch_id = _optional_text(self.branch_id, "graph_candidate.branch_id")
        evidence_refs = tuple(
            sorted(
                _checksum(item, "graph_candidate.evidence_refs")
                for item in self.evidence_refs
            )
        )
        if len(evidence_refs) != len(set(evidence_refs)):
            raise HarnessValidationError(
                "graph candidate evidence references must be unique",
                code="duplicate_graph_candidate_evidence",
            )
        payload = freeze_json(self.payload, "graph_candidate.payload")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "graph candidate payload must be an object",
                code="invalid_graph_candidate_payload",
            )
        object.__setattr__(self, "candidate_type", candidate_type)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "target_node_ids", target_node_ids)
        object.__setattr__(self, "branch_id", branch_id)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(
            self,
            "candidate_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    @property
    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.priority,
            "" if self.node_id is None else self.node_id,
            "" if self.node_instance_id is None else self.node_instance_id,
            self.candidate_type.value,
            "" if self.branch_id is None else self.branch_id,
            self.target_node_ids,
            self.candidate_checksum,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "candidate_type": self.candidate_type.value,
            "reason_code": self.reason_code,
            "priority": self.priority,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "target_node_ids": list(self.target_node_ids),
            "branch_id": self.branch_id,
            "evidence_refs": list(self.evidence_refs),
            "payload": thaw_json(self.payload),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "candidate_checksum": self.candidate_checksum,
        }


@dataclass(frozen=True, slots=True)
class GraphEvaluation:
    graph_checksum: str
    state_checksum: str
    context_checksum: str
    candidates: tuple[HarnessGraphCandidate, ...]
    ready_node_instance_ids: tuple[str, ...]
    running_node_instance_ids: tuple[str, ...]
    waiting_node_instance_ids: tuple[str, ...]
    terminal_node_instance_ids: tuple[str, ...]
    blocked_node_ids: tuple[str, ...]
    evaluator_version: str = HARNESS_GRAPH_EVALUATOR_VERSION
    evaluation_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "graph_checksum",
            _checksum(self.graph_checksum, "graph_evaluation.graph_checksum"),
        )
        object.__setattr__(
            self,
            "state_checksum",
            _checksum(self.state_checksum, "graph_evaluation.state_checksum"),
        )
        object.__setattr__(
            self,
            "context_checksum",
            _checksum(self.context_checksum, "graph_evaluation.context_checksum"),
        )
        raw_candidates = tuple(self.candidates)
        if not all(isinstance(item, HarnessGraphCandidate) for item in raw_candidates):
            raise TypeError("candidates must contain HarnessGraphCandidate values")
        candidates = tuple(sorted(raw_candidates, key=lambda item: item.sort_key))
        candidate_ids = [item.candidate_checksum for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise HarnessValidationError(
                "graph evaluation candidates must be unique",
                code="duplicate_graph_evaluation_candidate",
            )
        for field_name in (
            "ready_node_instance_ids",
            "running_node_instance_ids",
            "waiting_node_instance_ids",
            "terminal_node_instance_ids",
            "blocked_node_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _stable_text_tuple(
                    getattr(self, field_name), f"graph_evaluation.{field_name}"
                ),
            )
        if self.evaluator_version != HARNESS_GRAPH_EVALUATOR_VERSION:
            raise HarnessValidationError(
                "unsupported graph evaluator version",
                code="unsupported_graph_evaluator_version",
            )
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(
            self,
            "evaluation_checksum",
            canonical_checksum(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "evaluator_version": self.evaluator_version,
            "graph_checksum": self.graph_checksum,
            "state_checksum": self.state_checksum,
            "context_checksum": self.context_checksum,
            "candidates": [item.to_dict() for item in self.candidates],
            "ready_node_instance_ids": list(self.ready_node_instance_ids),
            "running_node_instance_ids": list(self.running_node_instance_ids),
            "waiting_node_instance_ids": list(self.waiting_node_instance_ids),
            "terminal_node_instance_ids": list(self.terminal_node_instance_ids),
            "blocked_node_ids": list(self.blocked_node_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "evaluation_checksum": self.evaluation_checksum,
        }


class WorkflowGraphEvaluator:
    evaluator_version = HARNESS_GRAPH_EVALUATOR_VERSION

    def evaluate(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        *,
        context: HarnessGraphEvaluationContext | None = None,
    ) -> GraphEvaluation:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if not isinstance(state, HarnessGraphState):
            raise TypeError("state must be HarnessGraphState")
        accepted_context = context or HarnessGraphEvaluationContext()
        if not isinstance(accepted_context, HarnessGraphEvaluationContext):
            raise TypeError("context must be HarnessGraphEvaluationContext")
        expected_graph_ref = HarnessGraphReference(
            graph.graph_id,
            graph.workflow_ref,
            graph.schema_version,
            graph.compiler_version,
            graph.condition_policy_version,
            graph.checksum,
        )
        if state.graph_ref != expected_graph_ref:
            raise HarnessValidationError(
                "graph evaluator state is pinned to another graph identity",
                code="graph_evaluator_graph_mismatch",
                details={
                    "expected": expected_graph_ref.to_dict(),
                    "actual": state.graph_ref.to_dict(),
                },
            )

        nodes_by_id = {node.node_id: node for node in graph.nodes}
        _validate_accepted_observations(
            graph,
            state,
            accepted_context,
            nodes_by_id,
        )
        instances_by_definition = _instances_by_definition(state.node_instances)
        instances_by_scope = _instances_by_definition_scope(state.node_instances)
        candidates: list[HarnessGraphCandidate] = []

        candidates.extend(
            self._compensation_candidates(
                graph,
                state,
                nodes_by_id,
            )
        )
        compensation_mode = _compensation_mode(state)
        if not compensation_mode:
            candidates.extend(self._join_candidates(graph, state, nodes_by_id))
            candidates.extend(
                self._control_candidates(
                    graph,
                    state,
                    accepted_context,
                    nodes_by_id,
                )
            )
            candidates.extend(
                self._activation_candidates(
                    graph,
                    state,
                    nodes_by_id,
                    instances_by_definition,
                    instances_by_scope,
                )
            )

        if not candidates:
            completion = self._run_projection_candidate(graph, state)
            if completion is not None:
                candidates.append(completion)

        activated_definitions = {
            candidate.node_id
            for candidate in candidates
            if candidate.candidate_type is HarnessGraphCandidateType.ACTIVATE_NODE
            and candidate.node_id is not None
        }
        blocked = tuple(
            node_id
            for node_id in sorted(nodes_by_id)
            if node_id not in instances_by_definition
            and node_id not in activated_definitions
        )
        return GraphEvaluation(
            graph_checksum=graph.checksum,
            state_checksum=state.projection_checksum,
            context_checksum=accepted_context.checksum,
            candidates=tuple(candidates),
            ready_node_instance_ids=state.ready_node_ids,
            running_node_instance_ids=state.running_node_ids,
            waiting_node_instance_ids=state.waiting_node_ids,
            terminal_node_instance_ids=state.terminal_node_ids,
            blocked_node_ids=blocked,
        )

    def _control_candidates(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        context: HarnessGraphEvaluationContext,
        nodes_by_id: Mapping[str, HarnessGraphNode],
    ) -> tuple[HarnessGraphCandidate, ...]:
        candidates: list[HarnessGraphCandidate] = []
        waits_by_node = {
            item.node_instance_id: item for item in state.wait_registrations
        }
        for instance in state.node_instances:
            definition = nodes_by_id[instance.identity.node_id]
            if definition.node_kind is HarnessGraphNodeKind.EXECUTABLE:
                continue
            if definition.node_kind in {
                HarnessGraphNodeKind.JOIN_ALL,
                HarnessGraphNodeKind.JOIN_ANY,
            }:
                continue
            if definition.node_kind is HarnessGraphNodeKind.WAIT:
                candidate = self._wait_candidate(
                    definition,
                    instance,
                    waits_by_node.get(instance.instance_id),
                )
                if candidate is not None:
                    candidates.append(candidate)
                continue
            if instance.status is not HarnessNodeInstanceStatus.READY:
                continue
            if not isinstance(definition, HarnessControlNode):
                raise TypeError("control node definition must be HarnessControlNode")
            if definition.node_kind is HarnessGraphNodeKind.CHOICE:
                candidates.append(
                    self._choice_candidate(graph, state, definition, instance, context)
                )
            elif definition.node_kind is HarnessGraphNodeKind.CHOICE_JOIN:
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.COMPLETE_CONTROL_NODE,
                        "selected_choice_branch_join_ready",
                        30,
                        node_id=definition.node_id,
                        node_instance_id=instance.instance_id,
                    )
                )
            elif definition.node_kind is HarnessGraphNodeKind.LOOP_JOIN:
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.COMPLETE_CONTROL_NODE,
                        "selected_loop_route_join_ready",
                        30,
                        node_id=definition.node_id,
                        node_instance_id=instance.instance_id,
                    )
                )
            elif definition.node_kind in {
                HarnessGraphNodeKind.FORK_ALL,
                HarnessGraphNodeKind.FORK_ANY,
            }:
                candidates.append(self._fork_candidate(graph, definition, instance))
            elif definition.node_kind is HarnessGraphNodeKind.LOOP_GUARD:
                candidates.append(
                    self._loop_candidate(definition, instance, state, context)
                )
            elif definition.node_kind is HarnessGraphNodeKind.MERGE:
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.APPLY_MERGE,
                        "merge_ready",
                        30,
                        node_id=definition.node_id,
                        node_instance_id=instance.instance_id,
                        payload=definition.merge.to_dict() if definition.merge else {},
                    )
                )
            elif definition.node_kind is HarnessGraphNodeKind.TERMINAL:
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.COMPLETE_CONTROL_NODE,
                        "terminal_control_node_ready",
                        30,
                        node_id=definition.node_id,
                        node_instance_id=instance.instance_id,
                    )
                )
        return tuple(candidates)

    def _choice_candidate(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        node: HarnessControlNode,
        instance: HarnessNodeInstanceState,
        context: HarnessGraphEvaluationContext,
    ) -> HarnessGraphCandidate:
        condition_context = _condition_context(
            graph,
            state,
            node,
            instance,
            context,
        )
        default_branch = None
        selected = None
        for branch in node.branches:
            if branch.is_default:
                default_branch = branch
                continue
            if branch.condition is not None and evaluate_condition(
                branch.condition,
                condition_context,
            ):
                selected = branch
                break
        selected = selected or default_branch
        if selected is None:
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.HALT_RUN,
                "no_matching_route",
                0,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                payload={"condition_policy_version": graph.condition_policy_version},
            )
        return HarnessGraphCandidate(
            HarnessGraphCandidateType.SELECT_CHOICE,
            "choice_branch_selected",
            20,
            node_id=node.node_id,
            node_instance_id=instance.instance_id,
            target_node_ids=selected.entry_node_ids,
            branch_id=selected.branch_id,
            payload={
                "condition_policy_version": graph.condition_policy_version,
                "branch_priority": selected.priority,
                "is_default": selected.is_default,
            },
        )

    def _fork_candidate(
        self,
        graph: NormalizedHarnessGraph,
        node: HarnessControlNode,
        instance: HarnessNodeInstanceState,
    ) -> HarnessGraphCandidate:
        branches = tuple(
            {
                "branch_id": branch.branch_id,
                "entry_node_ids": list(branch.entry_node_ids),
                "output_namespace": branch.output_namespace,
                "priority": branch.priority,
            }
            for branch in node.branches
        )
        targets = tuple(
            target for branch in node.branches for target in branch.entry_node_ids
        )
        join = _join_for_fork(graph, node.node_id)
        return HarnessGraphCandidate(
            HarnessGraphCandidateType.OPEN_FORK,
            "parallel_fork_ready",
            20,
            node_id=node.node_id,
            node_instance_id=instance.instance_id,
            target_node_ids=targets,
            payload={
                "fork_kind": node.node_kind.value,
                "branches": branches,
                "join_node_id": None if join is None else join.node_id,
                "failure_policy": (
                    None
                    if join is None or join.join is None
                    else join.join.failure_policy
                ),
            },
        )

    def _join_candidates(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        nodes_by_id: Mapping[str, HarnessGraphNode],
    ) -> tuple[HarnessGraphCandidate, ...]:
        candidates: list[HarnessGraphCandidate] = []
        instances_by_id = {item.instance_id: item for item in state.node_instances}
        for join_state in state.join_states:
            if join_state.status is not HarnessJoinStatus.OPEN:
                continue
            join_instance = instances_by_id[join_state.join_instance_id]
            definition = nodes_by_id[join_instance.identity.node_id]
            if (
                not isinstance(definition, HarnessControlNode)
                or definition.join is None
            ):
                raise HarnessValidationError(
                    "join state cannot resolve its normalized definition",
                    code="graph_evaluator_join_definition_mismatch",
                )
            if join_state.join_kind is HarnessJoinKind.ALL:
                if set(join_state.completed_branch_instances) != set(
                    join_state.required_branch_ids
                ):
                    continue
                failed_branches = tuple(
                    sorted(
                        branch_id
                        for branch_id, instance_id in join_state.completed_branch_instances.items()
                        if instances_by_id[instance_id].status
                        not in _SUCCESSFUL_NODE_STATUSES
                    )
                )
                evidence = tuple(join_state.terminal_event_refs.values())
                if failed_branches:
                    candidates.append(
                        HarnessGraphCandidate(
                            HarnessGraphCandidateType.FAIL_JOIN,
                            f"parallel_all_{definition.join.failure_policy}_failure",
                            10,
                            node_id=definition.node_id,
                            node_instance_id=join_state.join_instance_id,
                            evidence_refs=evidence,
                            payload={
                                "failure_policy": definition.join.failure_policy,
                                "failed_branch_ids": list(failed_branches),
                            },
                        )
                    )
                else:
                    candidates.append(
                        HarnessGraphCandidate(
                            HarnessGraphCandidateType.SATISFY_JOIN,
                            "parallel_all_join_satisfied",
                            10,
                            node_id=definition.node_id,
                            node_instance_id=join_state.join_instance_id,
                            evidence_refs=evidence,
                            payload={
                                "branch_instance_ids": thaw_json(
                                    join_state.completed_branch_instances
                                )
                            },
                        )
                    )
                continue

            successful = tuple(
                (
                    instances_by_id[instance_id].last_event_sequence,
                    instances_by_id[instance_id].identity.activation_ordinal,
                    branch_id,
                    instance_id,
                )
                for branch_id, instance_id in join_state.completed_branch_instances.items()
                if instances_by_id[instance_id].status in _SUCCESSFUL_NODE_STATUSES
            )
            if successful:
                _, _, branch_id, instance_id = min(successful)
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.SELECT_PARALLEL_WINNER,
                        "parallel_any_verified_winner",
                        5,
                        node_id=definition.node_id,
                        node_instance_id=join_state.join_instance_id,
                        branch_id=branch_id,
                        evidence_refs=(join_state.terminal_event_refs[branch_id],),
                        payload={"winner_node_instance_id": instance_id},
                    )
                )
            elif set(join_state.completed_branch_instances) == set(
                join_state.required_branch_ids
            ):
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.FAIL_JOIN,
                        "parallel_any_all_branches_failed",
                        10,
                        node_id=definition.node_id,
                        node_instance_id=join_state.join_instance_id,
                        evidence_refs=tuple(join_state.terminal_event_refs.values()),
                        payload={"failure_policy": definition.join.failure_policy},
                    )
                )
        return tuple(candidates)

    def _loop_candidate(
        self,
        node: HarnessControlNode,
        instance: HarnessNodeInstanceState,
        state: HarnessGraphState,
        context: HarnessGraphEvaluationContext,
    ) -> HarnessGraphCandidate:
        if node.loop is None:
            raise HarnessValidationError(
                "loop guard is missing its normalized contract",
                code="graph_evaluator_loop_contract_missing",
            )
        counter = _loop_counter_for(instance, state.loop_counters)
        completed = 0 if counter is None else counter.completed_iterations
        condition_context = _condition_context(
            None,
            state,
            node,
            instance,
            context,
        )
        should_continue = evaluate_condition(node.loop.condition, condition_context)
        if should_continue and completed < node.loop.max_iterations:
            iteration_scope = (
                instance.identity.branch_path,
                (
                    *instance.identity.iteration_vector,
                    HarnessLoopIteration(node.node_id, completed),
                ),
            )
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.START_LOOP_ITERATION,
                "loop_condition_matched",
                20,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                target_node_ids=node.loop.body_entry_node_ids,
                payload={
                    "iteration": completed,
                    "max_iterations": node.loop.max_iterations,
                    **_scope_payload(iteration_scope),
                },
            )
        if should_continue:
            if not node.loop.exhaustion_node_ids:
                return HarnessGraphCandidate(
                    HarnessGraphCandidateType.HALT_RUN,
                    "loop_budget_exhausted",
                    0,
                    node_id=node.node_id,
                    node_instance_id=instance.instance_id,
                    payload={
                        "completed_iterations": completed,
                        "max_iterations": node.loop.max_iterations,
                        **_scope_payload(_instance_scope(instance)),
                    },
                )
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.EXHAUST_LOOP,
                "loop_exhaustion_route_selected",
                20,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                target_node_ids=node.loop.exhaustion_node_ids,
                payload={
                    "completed_iterations": completed,
                    "max_iterations": node.loop.max_iterations,
                    **_scope_payload(_instance_scope(instance)),
                },
            )
        return HarnessGraphCandidate(
            HarnessGraphCandidateType.EXIT_LOOP,
            "loop_condition_not_matched",
            20,
            node_id=node.node_id,
            node_instance_id=instance.instance_id,
            target_node_ids=node.loop.exit_node_ids,
            payload={
                "completed_iterations": completed,
                **_scope_payload(_instance_scope(instance)),
            },
        )

    def _wait_candidate(
        self,
        node: HarnessGraphNode,
        instance: HarnessNodeInstanceState,
        registration,
    ) -> HarnessGraphCandidate | None:
        if not isinstance(node, HarnessControlNode) or node.wait is None:
            raise HarnessValidationError(
                "Wait node is missing its normalized contract",
                code="graph_evaluator_wait_contract_missing",
            )
        if instance.status is HarnessNodeInstanceStatus.READY and registration is None:
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.REGISTER_WAIT,
                "wait_registration_required",
                20,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                payload=node.wait.to_dict(),
            )
        if (
            instance.status is not HarnessNodeInstanceStatus.WAITING
            or registration is None
        ):
            return None
        if registration.status is HarnessWaitStatus.RESUMED:
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.RESUME_WAIT,
                "wait_signal_accepted",
                10,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                evidence_refs=(registration.resolution_event_ref,),
                payload={"wait_id": registration.wait_id, "resolution": "resumed"},
            )
        if registration.status is HarnessWaitStatus.TIMED_OUT:
            targets = ()
            if (
                node.wait.timeout_policy is not None
                and node.wait.timeout_policy.target_node_id is not None
            ):
                targets = (node.wait.timeout_policy.target_node_id,)
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.RESUME_WAIT,
                "wait_timeout_accepted",
                10,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                target_node_ids=targets,
                evidence_refs=(registration.resolution_event_ref,),
                payload={"wait_id": registration.wait_id, "resolution": "timed_out"},
            )
        if registration.status is HarnessWaitStatus.CANCELLED:
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.HALT_RUN,
                "wait_cancelled",
                0,
                node_id=node.node_id,
                node_instance_id=instance.instance_id,
                evidence_refs=(registration.resolution_event_ref,),
                payload={"wait_id": registration.wait_id},
            )
        return None

    def _activation_candidates(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        nodes_by_id: Mapping[str, HarnessGraphNode],
        instances_by_definition: Mapping[str, tuple[HarnessNodeInstanceState, ...]],
        instances_by_scope: Mapping[
            tuple[
                str,
                tuple[str, ...],
                tuple[HarnessLoopIteration, ...],
            ],
            tuple[HarnessNodeInstanceState, ...],
        ],
    ) -> tuple[HarnessGraphCandidate, ...]:
        incoming: dict[str, list[HarnessGraphEdge]] = defaultdict(list)
        outgoing: dict[str, list[HarnessGraphEdge]] = defaultdict(list)
        for edge in graph.edges:
            incoming[edge.target_id].append(edge)
            outgoing[edge.source_id].append(edge)
        candidates: list[HarnessGraphCandidate] = list(
            _selected_control_activation_candidates(
                state,
                nodes_by_id,
                instances_by_scope,
                outgoing,
            )
        )
        already_selected = {
            (
                item.node_id,
                tuple(item.payload.get("branch_path", ())),
                _iteration_vector_from_payload(item.payload),
            )
            for item in candidates
            if item.node_id is not None
        }
        for node_id in sorted(nodes_by_id):
            if node_id in graph.entry_node_ids:
                root_key = (node_id, (), ())
                if (
                    root_key not in instances_by_scope
                    and root_key not in already_selected
                ):
                    candidates.append(
                        HarnessGraphCandidate(
                            HarnessGraphCandidateType.ACTIVATE_NODE,
                            "graph_entry_ready",
                            40,
                            node_id=node_id,
                            payload=_scope_payload(((), ())),
                        )
                    )
                continue
            definition = nodes_by_id[node_id]
            if (
                isinstance(definition, HarnessControlNode)
                and definition.node_kind is HarnessGraphNodeKind.CHOICE_JOIN
            ):
                for scope, evidence_refs, payload in _choice_join_ready_scopes(
                    definition,
                    nodes_by_id,
                    instances_by_definition,
                ):
                    scoped_key = (node_id, *scope)
                    if (
                        scoped_key in instances_by_scope
                        or scoped_key in already_selected
                    ):
                        continue
                    candidates.append(
                        HarnessGraphCandidate(
                            HarnessGraphCandidateType.ACTIVATE_NODE,
                            "selected_choice_branch_succeeded",
                            40,
                            node_id=node_id,
                            evidence_refs=evidence_refs,
                            payload={**payload, **_scope_payload(scope)},
                        )
                    )
                continue
            if (
                isinstance(definition, HarnessControlNode)
                and definition.node_kind is HarnessGraphNodeKind.LOOP_JOIN
            ):
                for scope, evidence_refs, payload in _loop_join_ready_scopes(
                    definition,
                    nodes_by_id,
                    instances_by_definition,
                ):
                    scoped_key = (node_id, *scope)
                    if (
                        scoped_key in instances_by_scope
                        or scoped_key in already_selected
                    ):
                        continue
                    candidates.append(
                        HarnessGraphCandidate(
                            HarnessGraphCandidateType.ACTIVATE_NODE,
                            "selected_loop_route_succeeded",
                            40,
                            node_id=node_id,
                            evidence_refs=evidence_refs,
                            payload={**payload, **_scope_payload(scope)},
                        )
                    )
                continue
            dependency_edges = tuple(
                edge
                for edge in incoming.get(node_id, ())
                if edge.edge_kind in _FORWARD_DEPENDENCY_EDGE_KINDS
            )
            if not dependency_edges:
                continue
            eligible_scopes: (
                set[tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]]] | None
            ) = None
            for edge in dependency_edges:
                source_scopes = {
                    _instance_scope(item)
                    for item in instances_by_definition.get(edge.source_id, ())
                    if item.status in _SUCCESSFUL_NODE_STATUSES
                    and _edge_selected_for_instance(edge, item)
                }
                eligible_scopes = (
                    source_scopes
                    if eligible_scopes is None
                    else eligible_scopes.intersection(source_scopes)
                )
            for scope in sorted(eligible_scopes or (), key=_scope_sort_key):
                scoped_key = (node_id, *scope)
                if scoped_key in instances_by_scope or scoped_key in already_selected:
                    continue
                candidates.append(
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.ACTIVATE_NODE,
                        "predecessors_satisfied",
                        40,
                        node_id=node_id,
                        evidence_refs=tuple(
                            _terminal_evidence_for_definition(
                                edge.source_id,
                                instances_by_definition,
                                scope=scope,
                            )
                            for edge in dependency_edges
                        ),
                        payload=_scope_payload(scope),
                    )
                )
        return _admit_activation_candidates(state, tuple(candidates))

    def _compensation_candidates(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
        nodes_by_id: Mapping[str, HarnessGraphNode],
    ) -> tuple[HarnessGraphCandidate, ...]:
        if not _compensation_mode(state):
            return ()
        entries = state.compensation_stack
        if any(item.status is HarnessCompensationStatus.RUNNING for item in entries):
            return ()
        pending = tuple(
            item for item in entries if item.status is HarnessCompensationStatus.PENDING
        )
        if pending:
            entry = max(
                pending,
                key=lambda item: (item.effect_commit_sequence, item.entry_id),
            )
            origin = next(
                item
                for item in state.node_instances
                if item.instance_id == entry.origin_node_instance_id
            )
            binding = next(
                (
                    item
                    for item in graph.compensation_refs
                    if item.for_node_id == origin.identity.node_id
                ),
                None,
            )
            if binding is None:
                return (
                    HarnessGraphCandidate(
                        HarnessGraphCandidateType.HALT_RUN,
                        "compensation_binding_missing",
                        0,
                        node_id=origin.identity.node_id,
                        node_instance_id=origin.instance_id,
                        evidence_refs=(entry.effect_outcome_ref,),
                    ),
                )
            return (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.SCHEDULE_COMPENSATION,
                    "next_compensation_in_reverse_effect_order",
                    10,
                    node_id=binding.compensation_node_id,
                    target_node_ids=(binding.compensation_node_id,),
                    evidence_refs=(entry.effect_outcome_ref,),
                    payload={
                        "entry_id": entry.entry_id,
                        "origin_node_instance_id": origin.instance_id,
                        "handler_ref": binding.handler_ref.to_dict(),
                        "activity_ref": binding.activity_ref.to_dict(),
                        "idempotency_key": entry.idempotency_key,
                        "fencing_generation": entry.fencing_generation,
                    },
                ),
            )
        if any(
            item.status
            in {
                HarnessCompensationStatus.FAILED,
                HarnessCompensationStatus.INDETERMINATE,
            }
            for item in entries
        ):
            return (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.HALT_RUN,
                    "compensation_failed_or_indeterminate",
                    0,
                    evidence_refs=tuple(
                        item.outcome_ref
                        for item in entries
                        if item.outcome_ref is not None
                    ),
                ),
            )
        if entries and all(
            item.status is HarnessCompensationStatus.SUCCEEDED for item in entries
        ):
            return (
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.COMPLETE_RUN,
                    "all_compensations_succeeded",
                    50,
                    evidence_refs=tuple(
                        item.outcome_ref
                        for item in entries
                        if item.outcome_ref is not None
                    ),
                    payload={"outcome": "compensated"},
                ),
            )
        return ()

    def _run_projection_candidate(
        self,
        graph: NormalizedHarnessGraph,
        state: HarnessGraphState,
    ) -> HarnessGraphCandidate | None:
        if state.lifecycle is RunLifecycle.WAITING:
            return None
        active = tuple(item for item in state.node_instances if not item.is_terminal)
        if active:
            if (
                not any(item.is_ready or item.is_running for item in active)
                and any(item.is_waiting for item in active)
                and any(item.unresolved for item in state.wait_registrations)
            ):
                return HarnessGraphCandidate(
                    HarnessGraphCandidateType.PROJECT_RUN_WAITING,
                    "only_unresolved_waits_remain",
                    60,
                )
            return None
        instances_by_definition = _instances_by_definition(state.node_instances)
        if all(
            _definition_succeeded(node_id, instances_by_definition)
            for node_id in graph.terminal_node_ids
        ):
            return HarnessGraphCandidate(
                HarnessGraphCandidateType.COMPLETE_RUN,
                "graph_terminal_nodes_succeeded",
                60,
                evidence_refs=tuple(
                    _terminal_evidence_for_definition(
                        node_id,
                        instances_by_definition,
                    )
                    for node_id in graph.terminal_node_ids
                ),
                payload={"outcome": "succeeded"},
            )
        return None


def _instances_by_definition(
    instances: tuple[HarnessNodeInstanceState, ...],
) -> dict[str, tuple[HarnessNodeInstanceState, ...]]:
    grouped: dict[str, list[HarnessNodeInstanceState]] = defaultdict(list)
    for instance in instances:
        grouped[instance.identity.node_id].append(instance)
    return {
        node_id: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.identity.activation_ordinal,
                    item.instance_id,
                ),
            )
        )
        for node_id, values in grouped.items()
    }


def _instances_by_definition_scope(
    instances: tuple[HarnessNodeInstanceState, ...],
) -> dict[
    tuple[str, tuple[str, ...], tuple[HarnessLoopIteration, ...]],
    tuple[HarnessNodeInstanceState, ...],
]:
    grouped: dict[
        tuple[str, tuple[str, ...], tuple[HarnessLoopIteration, ...]],
        list[HarnessNodeInstanceState],
    ] = defaultdict(list)
    for instance in instances:
        grouped[(instance.identity.node_id, *_instance_scope(instance))].append(
            instance
        )
    return {
        key: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.identity.activation_ordinal,
                    item.instance_id,
                ),
            )
        )
        for key, values in grouped.items()
    }


def _validate_accepted_observations(
    graph: NormalizedHarnessGraph,
    state: HarnessGraphState,
    context: HarnessGraphEvaluationContext,
    nodes_by_id: Mapping[str, HarnessGraphNode],
) -> None:
    del graph
    instances_by_id = {item.instance_id: item for item in state.node_instances}
    logical_identities: set[tuple[str, int, str, str]] = set()
    for observation in context.observations:
        instance = instances_by_id.get(observation.node_instance_id)
        if instance is None:
            raise HarnessValidationError(
                "graph observation belongs to an unknown node instance",
                code="cross_node_graph_observation_rejected",
            )
        definition = nodes_by_id.get(instance.identity.node_id)
        if not isinstance(definition, HarnessExecutableNode):
            raise HarnessValidationError(
                "graph observation requires an executable node instance",
                code="graph_observation_node_kind_mismatch",
            )
        if observation.node_id != instance.identity.node_id:
            raise HarnessValidationError(
                "graph observation node definition does not match its instance",
                code="cross_node_graph_observation_rejected",
            )
        if observation.attempt != instance.attempt:
            raise HarnessValidationError(
                "graph observation belongs to another attempt",
                code="cross_attempt_graph_observation_rejected",
            )
        if observation.event_sequence > instance.last_event_sequence:
            raise HarnessValidationError(
                "graph observation has not been accepted by the current projection",
                code="uncommitted_graph_observation_rejected",
            )
        expected_contracts = _observation_contracts(
            observation.observation_type,
            definition,
        )
        if observation.contract_ref not in expected_contracts:
            raise HarnessValidationError(
                "graph observation contract does not match the pinned node binding",
                code="graph_observation_contract_mismatch",
                details={
                    "actual": observation.contract_ref.exact_ref,
                    "expected": sorted(item.exact_ref for item in expected_contracts),
                },
            )
        expected_evidence_kind = (
            HarnessEvidenceKind.ACTIVITY_RESULT
            if observation.observation_type
            in {
                HarnessGraphObservationType.VERIFIED_OUTPUT,
                HarnessGraphObservationType.WORKER_STATUS,
            }
            else HarnessEvidenceKind.GATE_RESULT
        )
        if not any(
            evidence.evidence_ref == observation.evidence_ref
            and evidence.kind is expected_evidence_kind
            and evidence.node_instance_id == observation.node_instance_id
            and evidence.attempt == observation.attempt
            and evidence.event_sequence == observation.event_sequence
            and evidence.contract_ref == observation.contract_ref
            and evidence.payload_ref == observation.payload_ref
            for evidence in instance.evidence_refs
        ):
            raise HarnessValidationError(
                "graph observation evidence is absent from the accepted node projection",
                code="unaccepted_graph_observation_rejected",
            )
        logical_identity = (
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
        if logical_identity in logical_identities:
            raise HarnessValidationError(
                "graph control context contains ambiguous accepted observations",
                code="ambiguous_graph_observation",
            )
        logical_identities.add(logical_identity)

    for observation in context.observations:
        if (
            observation.observation_type
            is not HarnessGraphObservationType.VERIFIED_OUTPUT
        ):
            continue
        instance = instances_by_id[observation.node_instance_id]
        definition = nodes_by_id[instance.identity.node_id]
        if not isinstance(definition, HarnessExecutableNode):
            raise AssertionError("verified output definition was validated above")
        declared_paths = _declared_control_fact_paths(definition)
        if observation.control_fact_paths != declared_paths:
            raise HarnessValidationError(
                "verified output control facts do not match the pinned Step declaration",
                code="graph_observation_control_fact_mismatch",
                details={
                    "actual": list(observation.control_fact_paths),
                    "expected": list(declared_paths),
                },
            )
        if instance.status not in _SUCCESSFUL_NODE_STATUSES:
            raise HarnessValidationError(
                "verified output cannot control routing before the node succeeds",
                code="unverified_graph_control_fact",
            )
        if not definition.gate_refs:
            raise HarnessValidationError(
                "routing control facts require an exact deterministic Gate binding",
                code="graph_control_fact_gate_missing",
            )
        gate_results = {
            item.contract_ref: item
            for item in context.for_node_instance(instance.instance_id)
            if item.attempt == observation.attempt
            and item.observation_type is HarnessGraphObservationType.GATE_RESULT
        }
        missing_gates = tuple(
            reference
            for reference in definition.gate_refs
            if reference not in gate_results
        )
        failed_gates = tuple(
            reference
            for reference in definition.gate_refs
            if reference in gate_results
            and gate_results[reference].payload.get("passed") is not True
        )
        stale_gates = tuple(
            reference
            for reference in definition.gate_refs
            if reference in gate_results
            and gate_results[reference].event_sequence < observation.event_sequence
        )
        misbound_gates = tuple(
            reference
            for reference in definition.gate_refs
            if reference in gate_results
            and gate_results[reference].payload.get("input_ref")
            != observation.payload_ref
        )
        if missing_gates or failed_gates or stale_gates or misbound_gates:
            raise HarnessValidationError(
                "routing control facts lack successful deterministic Gate evidence",
                code="unverified_graph_control_fact",
                details={
                    "missing_gates": [item.exact_ref for item in missing_gates],
                    "failed_gates": [item.exact_ref for item in failed_gates],
                    "stale_gates": [item.exact_ref for item in stale_gates],
                    "misbound_gates": [item.exact_ref for item in misbound_gates],
                },
            )


def _observation_contracts(
    observation_type: HarnessGraphObservationType,
    definition: HarnessExecutableNode,
) -> tuple[HarnessContractReference, ...]:
    if observation_type is HarnessGraphObservationType.VERIFIED_OUTPUT:
        return (definition.step_ref,)
    if observation_type is HarnessGraphObservationType.WORKER_STATUS:
        return (definition.worker_ref,)
    return definition.gate_refs


def _definition_succeeded(
    node_id: str,
    instances_by_definition: Mapping[str, tuple[HarnessNodeInstanceState, ...]],
) -> bool:
    instances = instances_by_definition.get(node_id, ())
    return bool(instances) and any(
        item.status in _SUCCESSFUL_NODE_STATUSES for item in instances
    )


def _terminal_evidence_for_definition(
    node_id: str,
    instances_by_definition: Mapping[str, tuple[HarnessNodeInstanceState, ...]],
    *,
    scope: tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]] | None = None,
) -> str:
    candidates = tuple(
        item
        for item in instances_by_definition.get(node_id, ())
        if item.status in _SUCCESSFUL_NODE_STATUSES
        and (scope is None or _instance_scope(item) == scope)
    )
    if not candidates:
        raise HarnessValidationError(
            "terminal evidence requested for an incomplete node definition",
            code="graph_evaluator_terminal_evidence_missing",
        )
    selected = max(
        candidates,
        key=lambda item: (item.last_event_sequence, item.identity.activation_ordinal),
    )
    evidence = tuple(
        item.evidence_ref
        for item in selected.evidence_refs
        if item.event_sequence == selected.last_event_sequence
    )
    return evidence[-1] if evidence else canonical_checksum(selected.to_dict())


def _edge_selected_for_instance(
    edge: HarnessGraphEdge,
    source: HarnessNodeInstanceState,
) -> bool:
    if edge.edge_kind not in {
        HarnessGraphEdgeKind.WAIT_RESUME,
        HarnessGraphEdgeKind.WAIT_TIMEOUT,
    }:
        return True
    resolution = source.metadata.get("wait_resolution")
    expected = (
        "resumed" if edge.edge_kind is HarnessGraphEdgeKind.WAIT_RESUME else "timed_out"
    )
    return resolution == expected


def _instance_scope(
    instance: HarnessNodeInstanceState,
) -> tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]]:
    return (
        instance.identity.branch_path,
        instance.identity.iteration_vector,
    )


def _scope_payload(
    scope: tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
) -> dict[str, Any]:
    branch_path, iteration_vector = scope
    return {
        "branch_path": list(branch_path),
        "iteration_vector": [item.to_dict() for item in iteration_vector],
    }


def _iteration_vector_from_payload(
    payload: Mapping[str, Any],
) -> tuple[HarnessLoopIteration, ...]:
    raw = payload.get("iteration_vector", ())
    if not isinstance(raw, tuple | list):
        return ()
    values: list[HarnessLoopIteration] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return ()
        loop_id = item.get("loop_id")
        iteration = item.get("iteration")
        if not isinstance(loop_id, str) or not isinstance(iteration, int):
            return ()
        values.append(HarnessLoopIteration(loop_id, iteration))
    return tuple(values)


def _scope_sort_key(
    scope: tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
) -> tuple[Any, ...]:
    branch_path, iteration_vector = scope
    return (
        branch_path,
        tuple((item.loop_id, item.iteration) for item in iteration_vector),
    )


def _admit_activation_candidates(
    state: HarnessGraphState,
    candidates: tuple[HarnessGraphCandidate, ...],
) -> tuple[HarnessGraphCandidate, ...]:
    if not candidates:
        return ()
    activation_budget = state.budgets.get("node_activations")
    active_budget = state.budgets.get("max_active_nodes")
    missing = tuple(
        name
        for name, counter in (
            ("node_activations", activation_budget),
            ("max_active_nodes", active_budget),
        )
        if counter is None
    )
    if missing:
        return (
            HarnessGraphCandidate(
                HarnessGraphCandidateType.HALT_RUN,
                "graph_budget_counter_missing",
                0,
                payload={"missing_counters": list(missing)},
            ),
        )
    if activation_budget is None or active_budget is None:
        raise AssertionError("Graph budget counters were validated above")
    if activation_budget.remaining <= 0:
        return (
            HarnessGraphCandidate(
                HarnessGraphCandidateType.HALT_RUN,
                "node_activation_budget_exhausted",
                0,
                payload={
                    "limit": activation_budget.limit,
                    "used": activation_budget.used,
                    "reserved": activation_budget.reserved,
                },
            ),
        )
    active_count = sum(1 for item in state.node_instances if not item.is_terminal)
    active_capacity = min(
        active_budget.remaining,
        max(0, active_budget.limit - active_count),
    )
    admitted = min(activation_budget.remaining, active_capacity)
    if admitted <= 0:
        return ()
    return tuple(sorted(candidates, key=lambda item: item.sort_key)[:admitted])


def _selected_control_activation_candidates(
    state: HarnessGraphState,
    nodes_by_id: Mapping[str, HarnessGraphNode],
    instances_by_scope: Mapping[
        tuple[
            str,
            tuple[str, ...],
            tuple[HarnessLoopIteration, ...],
        ],
        tuple[HarnessNodeInstanceState, ...],
    ],
    outgoing: Mapping[str, list[HarnessGraphEdge]],
) -> tuple[HarnessGraphCandidate, ...]:
    candidates: list[HarnessGraphCandidate] = []
    for instance in state.node_instances:
        if instance.status not in _SUCCESSFUL_NODE_STATUSES:
            continue
        definition = nodes_by_id[instance.identity.node_id]
        if not isinstance(definition, HarnessControlNode):
            continue
        selected_edges: tuple[HarnessGraphEdge, ...] = ()
        if definition.node_kind is HarnessGraphNodeKind.CHOICE:
            selected_branch_id = instance.metadata.get("selected_branch_id")
            if isinstance(selected_branch_id, str):
                selected_edges = tuple(
                    edge
                    for edge in outgoing.get(definition.node_id, ())
                    if edge.edge_kind
                    in {HarnessGraphEdgeKind.CHOICE, HarnessGraphEdgeKind.DEFAULT}
                    and edge.branch_id == selected_branch_id
                )
        elif definition.node_kind in {
            HarnessGraphNodeKind.FORK_ALL,
            HarnessGraphNodeKind.FORK_ANY,
        }:
            opened = instance.metadata.get("opened_branch_ids", ())
            if isinstance(opened, tuple) and all(
                isinstance(item, str) for item in opened
            ):
                opened_ids = frozenset(opened)
                selected_edges = tuple(
                    edge
                    for edge in outgoing.get(definition.node_id, ())
                    if edge.edge_kind is HarnessGraphEdgeKind.FORK_BRANCH
                    and edge.branch_id in opened_ids
                )
        for edge in sorted(
            selected_edges,
            key=lambda item: (
                item.priority,
                "" if item.branch_id is None else item.branch_id,
                item.target_id,
                item.edge_id,
            ),
        ):
            branch_path = instance.identity.branch_path + (
                () if edge.branch_id is None else (edge.branch_id,)
            )
            scope = (branch_path, instance.identity.iteration_vector)
            if (edge.target_id, *scope) in instances_by_scope:
                continue
            candidates.append(
                HarnessGraphCandidate(
                    HarnessGraphCandidateType.ACTIVATE_NODE,
                    "committed_control_selection_ready",
                    40,
                    node_id=edge.target_id,
                    branch_id=edge.branch_id,
                    evidence_refs=(canonical_checksum(instance.to_dict()),),
                    payload={
                        "source_node_instance_id": instance.instance_id,
                        "source_node_id": definition.node_id,
                        **_scope_payload(scope),
                    },
                )
            )
    return tuple(candidates)


def _choice_join_ready_scopes(
    definition: HarnessControlNode,
    nodes_by_id: Mapping[str, HarnessGraphNode],
    instances_by_definition: Mapping[str, tuple[HarnessNodeInstanceState, ...]],
) -> tuple[
    tuple[
        tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
        tuple[str, ...],
        dict[str, Any],
    ],
    ...,
]:
    choice_node_id = definition.metadata.get("choice_node_id")
    choice = (
        nodes_by_id.get(choice_node_id) if isinstance(choice_node_id, str) else None
    )
    if (
        not isinstance(choice, HarnessControlNode)
        or choice.node_kind is not HarnessGraphNodeKind.CHOICE
    ):
        raise HarnessValidationError(
            "Choice join cannot resolve its selector node",
            code="graph_evaluator_choice_join_mismatch",
            details={
                "choice_join_node_id": definition.node_id,
                "choice_node_id": choice_node_id,
            },
        )
    branches = {branch.branch_id: branch for branch in definition.branches}
    if tuple(branches) != tuple(branch.branch_id for branch in choice.branches):
        raise HarnessValidationError(
            "Choice join branches do not match their selector",
            code="graph_evaluator_choice_join_mismatch",
            details={"choice_join_node_id": definition.node_id},
        )

    ready: list[
        tuple[
            tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
            tuple[str, ...],
            dict[str, Any],
        ]
    ] = []
    for choice_instance in instances_by_definition.get(choice.node_id, ()):
        if choice_instance.status not in _SUCCESSFUL_NODE_STATUSES:
            continue
        selected_branch_id = choice_instance.metadata.get("selected_branch_id")
        branch = (
            branches.get(selected_branch_id)
            if isinstance(selected_branch_id, str)
            else None
        )
        if branch is None:
            raise HarnessValidationError(
                "completed Choice instance is missing its declared branch selection",
                code="graph_evaluator_choice_selection_missing",
                details={
                    "choice_node_id": choice.node_id,
                    "node_instance_id": choice_instance.instance_id,
                },
            )
        branch_scope = (
            (*choice_instance.identity.branch_path, selected_branch_id),
            choice_instance.identity.iteration_vector,
        )
        terminal_instances = tuple(
            sorted(
                (
                    item
                    for terminal_id in branch.terminal_node_ids
                    for item in instances_by_definition.get(terminal_id, ())
                    if item.status in _SUCCESSFUL_NODE_STATUSES
                    and _instance_scope(item) == branch_scope
                ),
                key=lambda item: (
                    item.last_event_sequence,
                    item.identity.activation_ordinal,
                    item.instance_id,
                ),
            )
        )
        if not terminal_instances:
            continue
        parent_scope = _instance_scope(choice_instance)
        evidence_refs = tuple(
            sorted(
                {
                    canonical_checksum(choice_instance.to_dict()),
                    *(
                        canonical_checksum(item.to_dict())
                        for item in terminal_instances
                    ),
                }
            )
        )
        ready.append(
            (
                parent_scope,
                evidence_refs,
                {
                    "choice_node_id": choice.node_id,
                    "choice_node_instance_id": choice_instance.instance_id,
                    "selected_branch_id": selected_branch_id,
                    "terminal_node_instance_ids": [
                        item.instance_id for item in terminal_instances
                    ],
                },
            )
        )
    return tuple(sorted(ready, key=lambda item: _scope_sort_key(item[0])))


def _loop_join_ready_scopes(
    definition: HarnessControlNode,
    nodes_by_id: Mapping[str, HarnessGraphNode],
    instances_by_definition: Mapping[str, tuple[HarnessNodeInstanceState, ...]],
) -> tuple[
    tuple[
        tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
        tuple[str, ...],
        dict[str, Any],
    ],
    ...,
]:
    loop_node_id = definition.metadata.get("loop_node_id")
    loop = nodes_by_id.get(loop_node_id) if isinstance(loop_node_id, str) else None
    if (
        not isinstance(loop, HarnessControlNode)
        or loop.node_kind is not HarnessGraphNodeKind.LOOP_GUARD
        or loop.loop is None
    ):
        raise HarnessValidationError(
            "Loop join cannot resolve its bounded Loop guard",
            code="graph_evaluator_loop_join_mismatch",
            details={
                "loop_join_node_id": definition.node_id,
                "loop_node_id": loop_node_id,
            },
        )

    declared_route_ids = {branch.branch_id for branch in definition.branches}
    selected_by_scope: dict[
        tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
        tuple[HarnessNodeInstanceState, str],
    ] = {}
    for loop_instance in instances_by_definition.get(loop.node_id, ()):
        if loop_instance.status not in _SUCCESSFUL_NODE_STATUSES:
            continue
        selected_route_id = loop_instance.metadata.get("selected_loop_route_id")
        if selected_route_id in {None, "continue"}:
            continue
        if (
            not isinstance(selected_route_id, str)
            or selected_route_id not in declared_route_ids
        ):
            raise HarnessValidationError(
                "completed Loop guard has an invalid durable route selection",
                code="graph_evaluator_loop_route_invalid",
                details={
                    "loop_node_id": loop.node_id,
                    "node_instance_id": loop_instance.instance_id,
                    "selected_route_id": selected_route_id,
                },
            )
        scope = _instance_scope(loop_instance)
        if scope in selected_by_scope:
            raise HarnessValidationError(
                "bounded Loop has multiple terminal route selections in one scope",
                code="graph_evaluator_loop_route_ambiguous",
                details={
                    "loop_node_id": loop.node_id,
                    "node_instance_ids": sorted(
                        {
                            selected_by_scope[scope][0].instance_id,
                            loop_instance.instance_id,
                        }
                    ),
                },
            )
        selected_by_scope[scope] = (loop_instance, selected_route_id)

    ready: list[
        tuple[
            tuple[tuple[str, ...], tuple[HarnessLoopIteration, ...]],
            tuple[str, ...],
            dict[str, Any],
        ]
    ] = []
    for scope, (loop_instance, selected_route_id) in sorted(
        selected_by_scope.items(),
        key=lambda item: _scope_sort_key(item[0]),
    ):
        completed_routes: list[tuple[str, tuple[HarnessNodeInstanceState, ...]]] = []
        for branch in definition.branches:
            terminal_instances = tuple(
                sorted(
                    (
                        item
                        for terminal_id in branch.terminal_node_ids
                        for item in instances_by_definition.get(terminal_id, ())
                        if item.status in _SUCCESSFUL_NODE_STATUSES
                        and _instance_scope(item) == scope
                    ),
                    key=lambda item: (
                        item.last_event_sequence,
                        item.identity.activation_ordinal,
                        item.instance_id,
                    ),
                )
            )
            if terminal_instances:
                completed_routes.append((branch.branch_id, terminal_instances))
        if not completed_routes:
            continue
        if len(completed_routes) > 1:
            raise HarnessValidationError(
                "bounded Loop has multiple successful exit routes in one scope",
                code="graph_evaluator_loop_route_ambiguous",
                details={
                    "loop_node_id": loop.node_id,
                    "node_instance_id": loop_instance.instance_id,
                    "route_ids": sorted(item[0] for item in completed_routes),
                },
            )
        route_id, terminal_instances = completed_routes[0]
        if route_id != selected_route_id:
            raise HarnessValidationError(
                "Loop terminal evidence does not match its durable route selection",
                code="graph_evaluator_loop_route_mismatch",
                details={
                    "loop_node_id": loop.node_id,
                    "selected_route_id": selected_route_id,
                    "completed_route_id": route_id,
                },
            )
        evidence_refs = tuple(
            sorted(
                {
                    canonical_checksum(loop_instance.to_dict()),
                    *(
                        canonical_checksum(item.to_dict())
                        for item in terminal_instances
                    ),
                }
            )
        )
        ready.append(
            (
                scope,
                evidence_refs,
                {
                    "loop_node_id": loop.node_id,
                    "loop_node_instance_id": loop_instance.instance_id,
                    "selected_route_id": route_id,
                    "terminal_node_instance_ids": [
                        item.instance_id for item in terminal_instances
                    ],
                },
            )
        )
    return tuple(ready)


def _condition_context(
    graph: NormalizedHarnessGraph | None,
    state: HarnessGraphState,
    node: HarnessControlNode,
    instance: HarnessNodeInstanceState,
    context: HarnessGraphEvaluationContext,
) -> dict[str, Any]:
    source_node_id = node.metadata.get("legacy_source_step_id")
    if not isinstance(source_node_id, str):
        source_node_id = _single_dependency_source(graph, node.node_id)
    source_instance = _source_instance_for_control(
        state,
        source_node_id,
        instance,
    )
    source_observations = (
        ()
        if source_instance is None
        else context.for_node_instance(source_instance.instance_id)
    )
    verified_output = _single_observation_payload(
        source_observations,
        HarnessGraphObservationType.VERIFIED_OUTPUT,
    )
    worker_status = _single_observation_payload(
        source_observations,
        HarnessGraphObservationType.WORKER_STATUS,
    )
    quality_verdict = _single_observation_payload(
        source_observations,
        HarnessGraphObservationType.QUALITY_VERDICT,
    )
    gate_results = {
        item.contract_ref.contract_id: thaw_json(item.payload)
        for item in source_observations
        if item.observation_type is HarnessGraphObservationType.GATE_RESULT
    }
    return {
        "graph": {
            "inputs": thaw_json(context.inputs),
            "outputs": _graph_verified_outputs(context),
        },
        "node": {
            "outputs": verified_output,
            "outcome": None
            if source_instance is None
            else source_instance.status.value,
        },
        "worker_result": worker_status,
        "quality_verdict": quality_verdict,
        "gate_results": gate_results,
        "run": {
            "lifecycle": state.lifecycle.value,
            "outcome": state.outcome.value,
        },
    }


def _source_instance_for_control(
    state: HarnessGraphState,
    source_node_id: str | None,
    control_instance: HarnessNodeInstanceState,
) -> HarnessNodeInstanceState | None:
    if source_node_id is None:
        return None
    matches = tuple(
        item
        for item in state.node_instances
        if item.identity.node_id == source_node_id
        and item.identity.branch_path == control_instance.identity.branch_path
        and item.identity.iteration_vector == control_instance.identity.iteration_vector
    )
    if not matches:
        return None
    return max(
        matches,
        key=lambda item: (
            item.last_event_sequence,
            item.identity.activation_ordinal,
            item.instance_id,
        ),
    )


def _single_observation_payload(
    observations: tuple[HarnessAcceptedGraphObservation, ...],
    observation_type: HarnessGraphObservationType,
) -> Any:
    matches = tuple(
        item for item in observations if item.observation_type is observation_type
    )
    if not matches:
        return (
            None
            if observation_type is not HarnessGraphObservationType.VERIFIED_OUTPUT
            else {}
        )
    if len(matches) > 1:
        raise HarnessValidationError(
            "graph control context contains duplicate observation kinds",
            code="ambiguous_graph_observation",
            details={"observation_type": observation_type.value},
        )
    return thaw_json(matches[0].payload)


def _graph_verified_outputs(
    context: HarnessGraphEvaluationContext,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for observation in context.observations:
        if (
            observation.observation_type
            is not HarnessGraphObservationType.VERIFIED_OUTPUT
        ):
            continue
        payload = thaw_json(observation.payload)
        if not isinstance(payload, Mapping):
            raise HarnessValidationError(
                "verified output observation payload must be an object",
                code="invalid_graph_observation_payload",
            )
        for key in sorted(payload):
            outputs[str(key)] = payload[key]
    return outputs


def _single_dependency_source(
    graph: NormalizedHarnessGraph | None,
    node_id: str,
) -> str | None:
    if graph is None:
        return None
    sources = tuple(
        sorted(
            {
                edge.source_id
                for edge in graph.edges
                if edge.target_id == node_id
                and edge.edge_kind is HarnessGraphEdgeKind.DEPENDENCY
            }
        )
    )
    return sources[0] if len(sources) == 1 else None


def _join_for_fork(
    graph: NormalizedHarnessGraph,
    fork_node_id: str,
) -> HarnessControlNode | None:
    matches = tuple(
        node
        for node in graph.nodes
        if isinstance(node, HarnessControlNode)
        and node.join is not None
        and node.join.fork_node_id == fork_node_id
    )
    return matches[0] if matches else None


def _loop_counter_for(
    instance: HarnessNodeInstanceState,
    counters: tuple[HarnessLoopCounterState, ...],
) -> HarnessLoopCounterState | None:
    matches = tuple(
        item
        for item in counters
        if item.loop_id == instance.identity.node_id
        and item.branch_path == instance.identity.branch_path
        and item.parent_iteration_vector == instance.identity.iteration_vector
    )
    if len(matches) > 1:
        raise HarnessValidationError(
            "loop guard scope resolves multiple counters",
            code="graph_evaluator_loop_counter_ambiguous",
        )
    return matches[0] if matches else None


def _compensation_mode(state: HarnessGraphState) -> bool:
    return state.metadata.get("execution_mode") == "compensating"


def _validate_status_payload(payload: Mapping[str, Any]) -> None:
    _exact_payload_keys(payload, {"status"}, "worker status")
    required_text(payload["status"], "graph_observation.payload.status")


def _validate_quality_payload(payload: Mapping[str, Any]) -> None:
    _exact_payload_keys(payload, {"passed", "score"}, "quality verdict")
    if not isinstance(payload["passed"], bool):
        raise HarnessValidationError(
            "quality verdict observation passed value must be boolean",
            code="invalid_graph_observation_payload",
        )
    score = payload["score"]
    if score is not None and (
        isinstance(score, bool)
        or not isinstance(score, int | float)
        or not math.isfinite(float(score))
        or not 0 <= float(score) <= 1
    ):
        raise HarnessValidationError(
            "quality verdict observation score must be between zero and one",
            code="invalid_graph_observation_payload",
        )


def _validate_gate_payload(payload: Mapping[str, Any]) -> None:
    _exact_payload_keys(
        payload,
        {"passed", "input_ref", "result_ref", "reason_code"},
        "Gate result",
    )
    if not isinstance(payload["passed"], bool):
        raise HarnessValidationError(
            "Gate result observation requires a boolean passed value",
            code="invalid_graph_observation_payload",
        )
    _checksum(payload["input_ref"], "graph_observation.payload.input_ref")
    _checksum(payload["result_ref"], "graph_observation.payload.result_ref")
    required_text(payload["reason_code"], "graph_observation.payload.reason_code")


def _declared_control_fact_paths(
    definition: HarnessExecutableNode,
) -> tuple[str, ...]:
    step_metadata = definition.metadata.get("step_metadata", {})
    if not isinstance(step_metadata, Mapping):
        raise HarnessValidationError(
            "normalized Step metadata must be an object",
            code="invalid_graph_control_fact_contract",
        )
    raw_paths = step_metadata.get("control_fact_paths", ())
    if not isinstance(raw_paths, tuple | list):
        raise HarnessValidationError(
            "control_fact_paths must be an array",
            code="invalid_graph_control_fact_contract",
        )
    return _control_fact_paths(raw_paths)


def _control_fact_paths(values: Any) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, tuple | list):
        raise HarnessValidationError(
            "control fact paths must be an array",
            code="invalid_graph_control_fact_contract",
        )
    paths = tuple(
        sorted(
            required_text(item, "graph_observation.control_fact_paths")
            for item in values
        )
    )
    if len(paths) != len(set(paths)):
        raise HarnessValidationError(
            "control fact paths must be unique",
            code="invalid_graph_control_fact_contract",
        )
    for path in paths:
        segments = path.split(".")
        if any(not segment for segment in segments):
            raise HarnessValidationError(
                "control fact path contains an empty segment",
                code="invalid_graph_control_fact_contract",
                details={"path": path},
            )
    for index, path in enumerate(paths):
        if any(other.startswith(f"{path}.") for other in paths[index + 1 :]):
            raise HarnessValidationError(
                "control fact paths cannot overlap",
                code="invalid_graph_control_fact_contract",
                details={"path": path},
            )
    return paths


def _project_control_fact_payload(
    payload: Mapping[str, Any],
    paths: tuple[str, ...],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    missing = object()
    for path in paths:
        value: Any = payload
        for segment in path.split("."):
            if not isinstance(value, Mapping) or segment not in value:
                value = missing
                break
            value = value[segment]
        if value is missing:
            raise HarnessValidationError(
                "verified control fact is absent from its payload",
                code="graph_observation_control_fact_missing",
                details={"path": path},
            )
        target = projected
        segments = path.split(".")
        for segment in segments[:-1]:
            child = target.setdefault(segment, {})
            if not isinstance(child, dict):
                raise HarnessValidationError(
                    "control fact paths overlap",
                    code="invalid_graph_control_fact_contract",
                )
            target = child
        target[segments[-1]] = value
    return projected


def _exact_payload_keys(
    payload: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} observation fields do not match its schema",
            code="invalid_graph_observation_payload",
            details={
                "missing": sorted(expected.difference(actual)),
                "unknown": sorted(str(item) for item in actual.difference(expected)),
            },
        )


def _stable_text_tuple(values, field_name: str) -> tuple[str, ...]:
    normalized = tuple(required_text(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            f"{field_name} must not contain duplicates",
            code="duplicate_graph_evaluation_identity",
        )
    return tuple(sorted(normalized))


def _ordered_unique_text_tuple(values, field_name: str) -> tuple[str, ...]:
    normalized = tuple(required_text(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise HarnessValidationError(
            f"{field_name} must not contain duplicates",
            code="duplicate_graph_evaluation_identity",
        )
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    return None if value is None else required_text(value, field_name)


def _checksum(value: Any, field_name: str) -> str:
    normalized = required_text(value, field_name)
    if _CHECKSUM_PATTERN.fullmatch(normalized) is None:
        raise HarnessValidationError(
            f"{field_name} must be a canonical sha256 reference",
            code="invalid_graph_evaluation_checksum",
        )
    return normalized


__all__ = [
    "GraphEvaluation",
    "HarnessAcceptedGraphObservation",
    "HarnessGraphCandidate",
    "HarnessGraphCandidateType",
    "HarnessGraphEvaluationContext",
    "HarnessGraphObservationType",
    "WorkflowGraphEvaluator",
]
