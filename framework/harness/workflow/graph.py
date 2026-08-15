from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeAlias

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.workflow.canonical import (
    canonical_checksum,
    freeze_json,
    optional_text,
    required_text,
    thaw_json,
)
from framework.harness.workflow.conditions import (
    ConditionAll,
    ConditionAny,
    ConditionPredicate,
    HarnessCondition,
    condition_from_dict,
)
from framework.harness.workflow.dsl import WaitKind, WaitTimeoutPolicy
from framework.harness.workflow.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


class HarnessGraphNodeKind(StrEnum):
    EXECUTABLE = "executable"
    CHOICE = "choice"
    CHOICE_JOIN = "choice_join"
    FORK_ALL = "fork_all"
    FORK_ANY = "fork_any"
    JOIN_ALL = "join_all"
    JOIN_ANY = "join_any"
    LOOP_GUARD = "loop_guard"
    LOOP_JOIN = "loop_join"
    WAIT = "wait"
    MERGE = "merge"
    TERMINAL = "terminal"


class HarnessGraphEdgeKind(StrEnum):
    DEPENDENCY = "dependency"
    CHOICE = "choice"
    DEFAULT = "default"
    FORK_BRANCH = "fork_branch"
    JOIN = "join"
    LOOP_BODY = "loop_body"
    LOOP_BACK = "loop_back"
    LOOP_EXIT = "loop_exit"
    LOOP_EXHAUSTED = "loop_exhausted"
    WAIT_RESUME = "wait_resume"
    WAIT_TIMEOUT = "wait_timeout"
    REPAIR = "repair"
    COMPENSATION = "compensation"


class HarnessContractKind(StrEnum):
    WORKFLOW = "workflow"
    STEP = "step"
    WORKER = "worker"
    GATE = "gate"
    ACTIVITY = "activity"
    SIDE_EFFECT = "side_effect"
    COMPENSATION = "compensation"
    MERGE = "merge"
    WAIT = "wait"
    TERMINAL_POLICY = "terminal_policy"
    RUN_OPERATION = "run_operation"


class HarnessMergeKind(StrEnum):
    PURE = "pure"
    AGGREGATION_STEP = "aggregation_step"


@dataclass(frozen=True, slots=True, order=True)
class HarnessContractReference:
    contract_kind: HarnessContractKind | str
    contract_id: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contract_kind", HarnessContractKind(self.contract_kind)
        )
        object.__setattr__(
            self, "contract_id", required_text(self.contract_id, "contract_ref.id")
        )
        version = required_text(self.version, "contract_ref.version")
        if version.lower() in {"current", "default", "latest", "stable"}:
            raise HarnessValidationError(
                "graph contract reference cannot use a moving version alias",
                code="graph_inexact_version_reference",
                details={"contract_id": self.contract_id, "version": version},
            )
        object.__setattr__(self, "version", version)

    @property
    def exact_ref(self) -> str:
        return f"{self.contract_id}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_kind": self.contract_kind.value,
            "contract_id": self.contract_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessContractReference":
        _exact_keys(
            value, {"contract_kind", "contract_id", "version"}, "contract reference"
        )
        return cls(
            contract_kind=value["contract_kind"],
            contract_id=value["contract_id"],
            version=value["version"],
        )


@dataclass(frozen=True, slots=True)
class HarnessBranch:
    branch_id: str
    entry_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    priority: int
    output_namespace: str
    condition: HarnessCondition | None = None
    is_default: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "branch_id", required_text(self.branch_id, "branch.branch_id")
        )
        object.__setattr__(
            self,
            "entry_node_ids",
            _text_tuple(
                self.entry_node_ids, "branch.entry_node_ids", allow_empty=False
            ),
        )
        object.__setattr__(
            self,
            "terminal_node_ids",
            _text_tuple(
                self.terminal_node_ids, "branch.terminal_node_ids", allow_empty=False
            ),
        )
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise HarnessValidationError(
                "branch priority must be an integer",
                code="invalid_branch_priority",
                details={"branch_id": self.branch_id},
            )
        object.__setattr__(
            self,
            "output_namespace",
            required_text(self.output_namespace, "branch.output_namespace"),
        )
        if self.condition is not None and not _is_condition(self.condition):
            raise HarnessValidationError(
                "branch condition must be a HarnessCondition",
                code="invalid_branch_condition",
                details={"branch_id": self.branch_id},
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "entry_node_ids": list(self.entry_node_ids),
            "terminal_node_ids": list(self.terminal_node_ids),
            "priority": self.priority,
            "output_namespace": self.output_namespace,
            "condition": None if self.condition is None else self.condition.to_dict(),
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessBranch":
        _exact_keys(
            value,
            {
                "branch_id",
                "entry_node_ids",
                "terminal_node_ids",
                "priority",
                "output_namespace",
                "condition",
                "is_default",
            },
            "branch",
        )
        return cls(
            branch_id=value["branch_id"],
            entry_node_ids=tuple(
                _array(value["entry_node_ids"], "branch.entry_node_ids")
            ),
            terminal_node_ids=tuple(
                _array(value["terminal_node_ids"], "branch.terminal_node_ids")
            ),
            priority=value["priority"],
            output_namespace=value["output_namespace"],
            condition=(
                None
                if value["condition"] is None
                else condition_from_dict(value["condition"])
            ),
            is_default=value["is_default"],
        )


@dataclass(frozen=True, slots=True)
class HarnessJoinContract:
    fork_node_id: str
    required_branch_ids: tuple[str, ...]
    failure_policy: str
    winner_policy: str | None = None
    merge_ref: HarnessContractReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fork_node_id",
            required_text(self.fork_node_id, "join.fork_node_id"),
        )
        object.__setattr__(
            self,
            "required_branch_ids",
            _text_tuple(
                self.required_branch_ids, "join.required_branch_ids", allow_empty=False
            ),
        )
        object.__setattr__(
            self,
            "failure_policy",
            required_text(self.failure_policy, "join.failure_policy"),
        )
        object.__setattr__(
            self,
            "winner_policy",
            optional_text(self.winner_policy, "join.winner_policy"),
        )
        if self.merge_ref is not None:
            _require_reference_kind(
                self.merge_ref, HarnessContractKind.MERGE, "join.merge_ref"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fork_node_id": self.fork_node_id,
            "required_branch_ids": list(self.required_branch_ids),
            "failure_policy": self.failure_policy,
            "winner_policy": self.winner_policy,
            "merge_ref": None if self.merge_ref is None else self.merge_ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessJoinContract":
        _exact_keys(
            value,
            {
                "fork_node_id",
                "required_branch_ids",
                "failure_policy",
                "winner_policy",
                "merge_ref",
            },
            "join contract",
        )
        return cls(
            fork_node_id=value["fork_node_id"],
            required_branch_ids=tuple(
                _array(value["required_branch_ids"], "join.required_branch_ids")
            ),
            failure_policy=value["failure_policy"],
            winner_policy=value["winner_policy"],
            merge_ref=(
                None
                if value["merge_ref"] is None
                else HarnessContractReference.from_dict(value["merge_ref"])
            ),
        )


@dataclass(frozen=True, slots=True)
class HarnessLoopContract:
    body_entry_node_ids: tuple[str, ...]
    body_terminal_node_ids: tuple[str, ...]
    condition: HarnessCondition
    max_iterations: int
    exit_node_ids: tuple[str, ...]
    exhaustion_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "body_entry_node_ids",
            _text_tuple(
                self.body_entry_node_ids, "loop.body_entry_node_ids", allow_empty=False
            ),
        )
        object.__setattr__(
            self,
            "body_terminal_node_ids",
            _text_tuple(
                self.body_terminal_node_ids,
                "loop.body_terminal_node_ids",
                allow_empty=False,
            ),
        )
        if not _is_condition(self.condition):
            raise HarnessValidationError(
                "loop contract condition must be a HarnessCondition",
                code="invalid_loop_condition",
            )
        if not isinstance(self.max_iterations, int) or isinstance(
            self.max_iterations, bool
        ):
            raise HarnessValidationError(
                "loop max_iterations must be an integer",
                code="invalid_loop_bound",
            )
        object.__setattr__(
            self,
            "exit_node_ids",
            _text_tuple(self.exit_node_ids, "loop.exit_node_ids", allow_empty=False),
        )
        object.__setattr__(
            self,
            "exhaustion_node_ids",
            _text_tuple(
                self.exhaustion_node_ids,
                "loop.exhaustion_node_ids",
                allow_empty=True,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_entry_node_ids": list(self.body_entry_node_ids),
            "body_terminal_node_ids": list(self.body_terminal_node_ids),
            "condition": self.condition.to_dict(),
            "max_iterations": self.max_iterations,
            "exit_node_ids": list(self.exit_node_ids),
            "exhaustion_node_ids": list(self.exhaustion_node_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessLoopContract":
        _exact_keys(
            value,
            {
                "body_entry_node_ids",
                "body_terminal_node_ids",
                "condition",
                "max_iterations",
                "exit_node_ids",
                "exhaustion_node_ids",
            },
            "loop contract",
        )
        return cls(
            body_entry_node_ids=tuple(
                _array(value["body_entry_node_ids"], "loop.body_entry_node_ids")
            ),
            body_terminal_node_ids=tuple(
                _array(value["body_terminal_node_ids"], "loop.body_terminal_node_ids")
            ),
            condition=condition_from_dict(value["condition"]),
            max_iterations=value["max_iterations"],
            exit_node_ids=tuple(_array(value["exit_node_ids"], "loop.exit_node_ids")),
            exhaustion_node_ids=tuple(
                _array(value["exhaustion_node_ids"], "loop.exhaustion_node_ids")
            ),
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitContract:
    wait_id: str
    kind: WaitKind | str
    correlation: Mapping[str, Any]
    signal_type: str
    signal_version: str
    tenant_scope_path: str
    identity_scope_path: str
    timeout_policy: WaitTimeoutPolicy | None = None
    deadline_input_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "wait_id", required_text(self.wait_id, "wait.wait_id"))
        object.__setattr__(self, "kind", WaitKind(self.kind))
        correlation = freeze_json(self.correlation, "wait.correlation")
        if not isinstance(correlation, Mapping) or not correlation:
            raise HarnessValidationError(
                "wait correlation must be a non-empty object",
                code="wait_correlation_missing",
            )
        object.__setattr__(self, "correlation", correlation)
        object.__setattr__(
            self, "signal_type", required_text(self.signal_type, "wait.signal_type")
        )
        object.__setattr__(
            self,
            "signal_version",
            required_text(self.signal_version, "wait.signal_version"),
        )
        object.__setattr__(
            self,
            "tenant_scope_path",
            required_text(self.tenant_scope_path, "wait.tenant_scope_path"),
        )
        object.__setattr__(
            self,
            "identity_scope_path",
            required_text(self.identity_scope_path, "wait.identity_scope_path"),
        )
        if self.timeout_policy is not None and not isinstance(
            self.timeout_policy, WaitTimeoutPolicy
        ):
            raise HarnessValidationError(
                "wait timeout policy must be WaitTimeoutPolicy",
                code="invalid_wait_timeout_policy",
            )
        object.__setattr__(
            self,
            "deadline_input_path",
            optional_text(self.deadline_input_path, "wait.deadline_input_path"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "wait_id": self.wait_id,
            "kind": self.kind.value,
            "correlation": thaw_json(self.correlation),
            "signal_type": self.signal_type,
            "signal_version": self.signal_version,
            "tenant_scope_path": self.tenant_scope_path,
            "identity_scope_path": self.identity_scope_path,
            "timeout_policy": (
                None if self.timeout_policy is None else self.timeout_policy.to_dict()
            ),
            "deadline_input_path": self.deadline_input_path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessWaitContract":
        _exact_keys(
            value,
            {
                "wait_id",
                "kind",
                "correlation",
                "signal_type",
                "signal_version",
                "tenant_scope_path",
                "identity_scope_path",
                "timeout_policy",
                "deadline_input_path",
            },
            "wait contract",
        )
        timeout = value["timeout_policy"]
        if timeout is not None:
            _exact_keys(timeout, {"action", "target_node_id"}, "wait timeout policy")
        return cls(
            wait_id=value["wait_id"],
            kind=value["kind"],
            correlation=value["correlation"],
            signal_type=value["signal_type"],
            signal_version=value["signal_version"],
            tenant_scope_path=value["tenant_scope_path"],
            identity_scope_path=value["identity_scope_path"],
            timeout_policy=(
                None
                if timeout is None
                else WaitTimeoutPolicy(
                    action=timeout["action"],
                    target_node_id=timeout["target_node_id"],
                )
            ),
            deadline_input_path=value["deadline_input_path"],
        )


@dataclass(frozen=True, slots=True)
class HarnessMergeContract:
    merge_kind: HarnessMergeKind | str
    input_branch_ids: tuple[str, ...]
    output_keys: tuple[str, ...]
    merge_ref: HarnessContractReference | None = None
    aggregation_node_id: str | None = None

    def __post_init__(self) -> None:
        merge_kind = HarnessMergeKind(self.merge_kind)
        input_branches = _text_tuple(
            self.input_branch_ids,
            "merge.input_branch_ids",
            allow_empty=False,
        )
        output_keys = _text_tuple(
            self.output_keys, "merge.output_keys", allow_empty=False
        )
        aggregation_node_id = optional_text(
            self.aggregation_node_id,
            "merge.aggregation_node_id",
        )
        if merge_kind == HarnessMergeKind.PURE:
            if self.merge_ref is None or aggregation_node_id is not None:
                raise HarnessValidationError(
                    "pure merge requires merge_ref and forbids aggregation_node_id",
                    code="invalid_merge_contract",
                )
            _require_reference_kind(
                self.merge_ref, HarnessContractKind.MERGE, "merge.merge_ref"
            )
        elif self.merge_ref is not None or aggregation_node_id is None:
            raise HarnessValidationError(
                "aggregation-step merge requires aggregation_node_id and forbids merge_ref",
                code="invalid_merge_contract",
            )
        object.__setattr__(self, "merge_kind", merge_kind)
        object.__setattr__(self, "input_branch_ids", input_branches)
        object.__setattr__(self, "output_keys", output_keys)
        object.__setattr__(self, "aggregation_node_id", aggregation_node_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merge_kind": self.merge_kind.value,
            "input_branch_ids": list(self.input_branch_ids),
            "output_keys": list(self.output_keys),
            "merge_ref": None if self.merge_ref is None else self.merge_ref.to_dict(),
            "aggregation_node_id": self.aggregation_node_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessMergeContract":
        _exact_keys(
            value,
            {
                "merge_kind",
                "input_branch_ids",
                "output_keys",
                "merge_ref",
                "aggregation_node_id",
            },
            "merge contract",
        )
        return cls(
            merge_kind=value["merge_kind"],
            input_branch_ids=tuple(
                _array(value["input_branch_ids"], "merge.input_branch_ids")
            ),
            output_keys=tuple(_array(value["output_keys"], "merge.output_keys")),
            merge_ref=(
                None
                if value["merge_ref"] is None
                else HarnessContractReference.from_dict(value["merge_ref"])
            ),
            aggregation_node_id=value["aggregation_node_id"],
        )


@dataclass(frozen=True, slots=True)
class HarnessCompensationReference:
    binding_id: str
    for_node_id: str
    compensation_node_id: str
    handler_ref: HarnessContractReference
    activity_ref: HarnessContractReference
    scope: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "binding_id",
            required_text(self.binding_id, "compensation.binding_id"),
        )
        object.__setattr__(
            self,
            "for_node_id",
            required_text(self.for_node_id, "compensation.for_node_id"),
        )
        object.__setattr__(
            self,
            "compensation_node_id",
            required_text(
                self.compensation_node_id, "compensation.compensation_node_id"
            ),
        )
        _require_reference_kind(
            self.handler_ref,
            HarnessContractKind.COMPENSATION,
            "compensation.handler_ref",
        )
        _require_reference_kind(
            self.activity_ref,
            HarnessContractKind.ACTIVITY,
            "compensation.activity_ref",
        )
        object.__setattr__(
            self, "scope", required_text(self.scope, "compensation.scope")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "for_node_id": self.for_node_id,
            "compensation_node_id": self.compensation_node_id,
            "handler_ref": self.handler_ref.to_dict(),
            "activity_ref": self.activity_ref.to_dict(),
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessCompensationReference":
        _exact_keys(
            value,
            {
                "binding_id",
                "for_node_id",
                "compensation_node_id",
                "handler_ref",
                "activity_ref",
                "scope",
            },
            "compensation reference",
        )
        return cls(
            binding_id=value["binding_id"],
            for_node_id=value["for_node_id"],
            compensation_node_id=value["compensation_node_id"],
            handler_ref=HarnessContractReference.from_dict(value["handler_ref"]),
            activity_ref=HarnessContractReference.from_dict(value["activity_ref"]),
            scope=value["scope"],
        )


@dataclass(frozen=True, slots=True)
class HarnessExecutableNode:
    node_id: str
    step_id: str
    declaration_order: int
    step_ref: HarnessContractReference
    worker_ref: HarnessContractReference
    activity_ref: HarnessContractReference
    gate_refs: tuple[HarnessContractReference, ...] = ()
    side_effect_ref: HarnessContractReference | None = None
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    node_kind: HarnessGraphNodeKind = field(
        default=HarnessGraphNodeKind.EXECUTABLE,
        init=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", required_text(self.node_id, "node.node_id"))
        object.__setattr__(self, "step_id", required_text(self.step_id, "node.step_id"))
        _declaration_order(self.declaration_order)
        _require_reference_kind(
            self.step_ref, HarnessContractKind.STEP, "node.step_ref"
        )
        _require_reference_kind(
            self.worker_ref, HarnessContractKind.WORKER, "node.worker_ref"
        )
        _require_reference_kind(
            self.activity_ref, HarnessContractKind.ACTIVITY, "node.activity_ref"
        )
        gate_refs = tuple(self.gate_refs)
        for reference in gate_refs:
            _require_reference_kind(
                reference, HarnessContractKind.GATE, "node.gate_refs"
            )
        if self.side_effect_ref is not None:
            _require_reference_kind(
                self.side_effect_ref,
                HarnessContractKind.SIDE_EFFECT,
                "node.side_effect_ref",
            )
        object.__setattr__(
            self, "gate_refs", tuple(sorted(gate_refs, key=lambda ref: ref.exact_ref))
        )
        object.__setattr__(
            self,
            "input_keys",
            _text_tuple(self.input_keys, "node.input_keys", allow_empty=True),
        )
        object.__setattr__(
            self,
            "output_keys",
            _text_tuple(self.output_keys, "node.output_keys", allow_empty=True),
        )
        metadata = freeze_json(self.metadata, "node.metadata")
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError(
                "node metadata must be an object",
                code="invalid_graph_metadata",
            )
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_kind": self.node_kind.value,
            "step_id": self.step_id,
            "declaration_order": self.declaration_order,
            "step_ref": self.step_ref.to_dict(),
            "worker_ref": self.worker_ref.to_dict(),
            "activity_ref": self.activity_ref.to_dict(),
            "gate_refs": [reference.to_dict() for reference in self.gate_refs],
            "side_effect_ref": (
                None if self.side_effect_ref is None else self.side_effect_ref.to_dict()
            ),
            "input_keys": list(self.input_keys),
            "output_keys": list(self.output_keys),
            "metadata": thaw_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class HarnessControlNode:
    node_id: str
    node_kind: HarnessGraphNodeKind | str
    declaration_order: int
    branches: tuple[HarnessBranch, ...] = ()
    join: HarnessJoinContract | None = None
    loop: HarnessLoopContract | None = None
    wait: HarnessWaitContract | None = None
    merge: HarnessMergeContract | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        node_id = required_text(self.node_id, "node.node_id")
        node_kind = HarnessGraphNodeKind(self.node_kind)
        if node_kind == HarnessGraphNodeKind.EXECUTABLE:
            raise HarnessValidationError(
                "control node cannot use executable node kind",
                code="invalid_control_node_kind",
                details={"node_id": node_id},
            )
        _declaration_order(self.declaration_order)
        branches = tuple(self.branches)
        if not all(isinstance(branch, HarnessBranch) for branch in branches):
            raise HarnessValidationError(
                "control node branches must contain HarnessBranch values",
                code="invalid_branch_contract",
            )
        expected_contract = {
            HarnessGraphNodeKind.CHOICE: "branches",
            HarnessGraphNodeKind.CHOICE_JOIN: "branches",
            HarnessGraphNodeKind.FORK_ALL: "branches",
            HarnessGraphNodeKind.FORK_ANY: "branches",
            HarnessGraphNodeKind.JOIN_ALL: "join",
            HarnessGraphNodeKind.JOIN_ANY: "join",
            HarnessGraphNodeKind.LOOP_GUARD: "loop",
            HarnessGraphNodeKind.LOOP_JOIN: "branches",
            HarnessGraphNodeKind.WAIT: "wait",
            HarnessGraphNodeKind.MERGE: "merge",
            HarnessGraphNodeKind.TERMINAL: None,
        }[node_kind]
        present = {
            name
            for name, value in (
                ("branches", branches if branches else None),
                ("join", self.join),
                ("loop", self.loop),
                ("wait", self.wait),
                ("merge", self.merge),
            )
            if value is not None
        }
        if expected_contract is None:
            valid = not present
        else:
            valid = present == {expected_contract}
        if not valid:
            raise HarnessValidationError(
                "control node contract does not match node kind",
                code="invalid_control_node_contract",
                details={
                    "node_id": node_id,
                    "node_kind": node_kind.value,
                    "present": sorted(present),
                },
            )
        metadata = freeze_json(self.metadata, "node.metadata")
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError(
                "node metadata must be an object",
                code="invalid_graph_metadata",
            )
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_kind", node_kind)
        object.__setattr__(
            self,
            "branches",
            tuple(
                sorted(branches, key=lambda branch: (branch.priority, branch.branch_id))
            ),
        )
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_kind": self.node_kind.value,
            "declaration_order": self.declaration_order,
            "branches": [branch.to_dict() for branch in self.branches],
            "join": None if self.join is None else self.join.to_dict(),
            "loop": None if self.loop is None else self.loop.to_dict(),
            "wait": None if self.wait is None else self.wait.to_dict(),
            "merge": None if self.merge is None else self.merge.to_dict(),
            "metadata": thaw_json(self.metadata),
        }


HarnessGraphNode: TypeAlias = HarnessExecutableNode | HarnessControlNode


@dataclass(frozen=True, slots=True)
class HarnessGraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_kind: HarnessGraphEdgeKind | str
    priority: int = 0
    condition: HarnessCondition | None = None
    branch_id: str | None = None
    loop_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", required_text(self.edge_id, "edge.edge_id"))
        object.__setattr__(
            self, "source_id", required_text(self.source_id, "edge.source_id")
        )
        object.__setattr__(
            self, "target_id", required_text(self.target_id, "edge.target_id")
        )
        object.__setattr__(self, "edge_kind", HarnessGraphEdgeKind(self.edge_kind))
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise HarnessValidationError(
                "edge priority must be an integer",
                code="invalid_edge_priority",
                details={"edge_id": self.edge_id},
            )
        if self.condition is not None and not _is_condition(self.condition):
            raise HarnessValidationError(
                "edge condition must be a HarnessCondition",
                code="invalid_edge_condition",
                details={"edge_id": self.edge_id},
            )
        object.__setattr__(
            self, "branch_id", optional_text(self.branch_id, "edge.branch_id")
        )
        object.__setattr__(self, "loop_id", optional_text(self.loop_id, "edge.loop_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_kind": self.edge_kind.value,
            "priority": self.priority,
            "condition": None if self.condition is None else self.condition.to_dict(),
            "branch_id": self.branch_id,
            "loop_id": self.loop_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessGraphEdge":
        _exact_keys(
            value,
            {
                "edge_id",
                "source_id",
                "target_id",
                "edge_kind",
                "priority",
                "condition",
                "branch_id",
                "loop_id",
            },
            "edge",
        )
        return cls(
            edge_id=value["edge_id"],
            source_id=value["source_id"],
            target_id=value["target_id"],
            edge_kind=value["edge_kind"],
            priority=value["priority"],
            condition=(
                None
                if value["condition"] is None
                else condition_from_dict(value["condition"])
            ),
            branch_id=value["branch_id"],
            loop_id=value["loop_id"],
        )


@dataclass(frozen=True, slots=True)
class NormalizedHarnessGraph:
    graph_id: str
    workflow_id: str
    workflow_version: str
    workflow_ref: HarnessContractReference
    nodes: tuple[HarnessGraphNode, ...]
    edges: tuple[HarnessGraphEdge, ...]
    entry_node_ids: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    input_keys: tuple[str, ...] = ()
    terminal_output_keys: tuple[str, ...] = ()
    compensation_refs: tuple[HarnessCompensationReference, ...] = ()
    terminal_policy_ref: HarnessContractReference | None = None
    terminal_policy: HarnessTerminalSideEffectPolicy | None = None
    schema_version: str = NORMALIZED_HARNESS_GRAPH_SCHEMA
    compiler_version: str = HARNESS_GRAPH_COMPILER_VERSION
    condition_policy_version: str = HARNESS_CONDITION_POLICY_VERSION
    checksum: str | None = None

    def __post_init__(self) -> None:
        graph_id = required_text(self.graph_id, "graph.graph_id")
        workflow_id = required_text(self.workflow_id, "graph.workflow_id")
        workflow_version = required_text(
            self.workflow_version, "graph.workflow_version"
        )
        _require_reference_kind(
            self.workflow_ref,
            HarnessContractKind.WORKFLOW,
            "graph.workflow_ref",
        )
        if (
            self.workflow_ref.contract_id != workflow_id
            or self.workflow_ref.version != workflow_version
        ):
            raise HarnessValidationError(
                "workflow_ref must match workflow_id and workflow_version",
                code="graph_workflow_reference_mismatch",
            )
        nodes = tuple(self.nodes)
        if not nodes or not all(
            isinstance(node, HarnessExecutableNode | HarnessControlNode)
            for node in nodes
        ):
            raise HarnessValidationError(
                "normalized graph must contain graph nodes",
                code="invalid_normalized_graph_nodes",
            )
        edges = tuple(self.edges)
        if not all(isinstance(edge, HarnessGraphEdge) for edge in edges):
            raise HarnessValidationError(
                "normalized graph edges must contain HarnessGraphEdge values",
                code="invalid_normalized_graph_edges",
            )
        compensation_refs = tuple(self.compensation_refs)
        if not all(
            isinstance(reference, HarnessCompensationReference)
            for reference in compensation_refs
        ):
            raise HarnessValidationError(
                "normalized graph compensation refs are invalid",
                code="invalid_compensation_contract",
            )
        if self.terminal_policy_ref is not None:
            _require_reference_kind(
                self.terminal_policy_ref,
                HarnessContractKind.TERMINAL_POLICY,
                "graph.terminal_policy_ref",
            )
        if self.terminal_policy is not None:
            if not isinstance(
                self.terminal_policy,
                HarnessTerminalSideEffectPolicy,
            ):
                raise HarnessValidationError(
                    "normalized graph terminal policy is invalid",
                    code="invalid_terminal_policy_contract",
                )
            expected_terminal_ref = HarnessContractReference(
                HarnessContractKind.TERMINAL_POLICY,
                self.terminal_policy.policy_id,
                self.terminal_policy.version,
            )
            if self.terminal_policy_ref != expected_terminal_ref:
                raise HarnessValidationError(
                    "terminal policy snapshot does not match its exact reference",
                    code="terminal_policy_reference_mismatch",
                    details={
                        "expected": expected_terminal_ref.exact_ref,
                        "actual": (
                            None
                            if self.terminal_policy_ref is None
                            else self.terminal_policy_ref.exact_ref
                        ),
                    },
                )
        if self.schema_version != NORMALIZED_HARNESS_GRAPH_SCHEMA:
            raise HarnessValidationError(
                "unsupported normalized graph schema",
                code="unsupported_graph_schema",
                details={"schema_version": str(self.schema_version)},
            )
        if self.compiler_version != HARNESS_GRAPH_COMPILER_VERSION:
            raise HarnessValidationError(
                "unsupported graph compiler version",
                code="unsupported_graph_compiler",
                details={"compiler_version": str(self.compiler_version)},
            )
        if self.condition_policy_version != HARNESS_CONDITION_POLICY_VERSION:
            raise HarnessValidationError(
                "unsupported graph condition policy version",
                code="unsupported_condition_policy",
                details={
                    "condition_policy_version": str(self.condition_policy_version)
                },
            )
        nodes = tuple(
            sorted(nodes, key=lambda node: (node.node_id, node.node_kind.value))
        )
        edges = tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.source_id,
                    edge.priority,
                    edge.target_id,
                    edge.edge_kind.value,
                    edge.edge_id,
                ),
            )
        )
        compensation_refs = tuple(
            sorted(compensation_refs, key=lambda reference: reference.binding_id)
        )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "workflow_version", workflow_version)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(
            self,
            "entry_node_ids",
            tuple(
                sorted(
                    _text_tuple(
                        self.entry_node_ids, "graph.entry_node_ids", allow_empty=False
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "terminal_node_ids",
            tuple(
                sorted(
                    _text_tuple(
                        self.terminal_node_ids,
                        "graph.terminal_node_ids",
                        allow_empty=False,
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "input_keys",
            tuple(
                sorted(
                    _text_tuple(self.input_keys, "graph.input_keys", allow_empty=True)
                )
            ),
        )
        object.__setattr__(
            self,
            "terminal_output_keys",
            tuple(
                sorted(
                    _text_tuple(
                        self.terminal_output_keys,
                        "graph.terminal_output_keys",
                        allow_empty=True,
                    )
                )
            ),
        )
        object.__setattr__(self, "compensation_refs", compensation_refs)
        calculated = canonical_checksum(self.checksum_projection())
        if self.checksum is not None and self.checksum != calculated:
            raise HarnessValidationError(
                "normalized graph checksum does not match canonical content",
                code="graph_checksum_mismatch",
                details={"expected": calculated, "actual": str(self.checksum)},
            )
        object.__setattr__(self, "checksum", calculated)

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "graph_id": self.graph_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "workflow_ref": self.workflow_ref.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "entry_node_ids": list(self.entry_node_ids),
            "terminal_node_ids": list(self.terminal_node_ids),
            "input_keys": list(self.input_keys),
            "terminal_output_keys": list(self.terminal_output_keys),
            "compensation_refs": [
                reference.to_dict() for reference in self.compensation_refs
            ],
            "terminal_policy_ref": (
                None
                if self.terminal_policy_ref is None
                else self.terminal_policy_ref.to_dict()
            ),
            "terminal_policy": (
                None if self.terminal_policy is None else self.terminal_policy.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "checksum": self.checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedHarnessGraph":
        payload = dict(value)
        expected_fields = {
            "schema_version",
            "compiler_version",
            "condition_policy_version",
            "graph_id",
            "workflow_id",
            "workflow_version",
            "workflow_ref",
            "nodes",
            "edges",
            "entry_node_ids",
            "terminal_node_ids",
            "input_keys",
            "terminal_output_keys",
            "compensation_refs",
            "terminal_policy_ref",
            "terminal_policy",
            "checksum",
        }
        missing_fields = expected_fields.difference(payload)
        legacy_missing_fields = (
            {"terminal_policy"},
            {"input_keys", "terminal_output_keys", "terminal_policy"},
        )
        if missing_fields in legacy_missing_fields:
            _exact_keys(
                payload,
                expected_fields.difference(missing_fields),
                "legacy normalized graph",
            )
            supplied_checksum = payload["checksum"]
            legacy_projection = {
                key: item for key, item in payload.items() if key != "checksum"
            }
            expected_checksum = canonical_checksum(legacy_projection)
            if supplied_checksum != expected_checksum:
                raise HarnessValidationError(
                    "legacy normalized graph checksum does not match canonical content",
                    code="graph_checksum_mismatch",
                    details={
                        "expected": expected_checksum,
                        "actual": str(supplied_checksum),
                    },
                )
            payload.setdefault("input_keys", ())
            payload.setdefault("terminal_output_keys", ())
            payload["terminal_policy"] = None
            payload["checksum"] = None
        _exact_keys(
            payload,
            expected_fields,
            "normalized graph",
        )
        return cls(
            schema_version=payload["schema_version"],
            compiler_version=payload["compiler_version"],
            condition_policy_version=payload["condition_policy_version"],
            graph_id=payload["graph_id"],
            workflow_id=payload["workflow_id"],
            workflow_version=payload["workflow_version"],
            workflow_ref=HarnessContractReference.from_dict(payload["workflow_ref"]),
            nodes=tuple(
                graph_node_from_dict(item)
                for item in _array(payload["nodes"], "normalized_graph.nodes")
            ),
            edges=tuple(
                HarnessGraphEdge.from_dict(item)
                for item in _array(payload["edges"], "normalized_graph.edges")
            ),
            entry_node_ids=tuple(
                _array(payload["entry_node_ids"], "normalized_graph.entry_node_ids")
            ),
            terminal_node_ids=tuple(
                _array(
                    payload["terminal_node_ids"], "normalized_graph.terminal_node_ids"
                )
            ),
            input_keys=tuple(
                _array(payload["input_keys"], "normalized_graph.input_keys")
            ),
            terminal_output_keys=tuple(
                _array(
                    payload["terminal_output_keys"],
                    "normalized_graph.terminal_output_keys",
                )
            ),
            compensation_refs=tuple(
                HarnessCompensationReference.from_dict(item)
                for item in _array(
                    payload["compensation_refs"],
                    "normalized_graph.compensation_refs",
                )
            ),
            terminal_policy_ref=(
                None
                if payload["terminal_policy_ref"] is None
                else HarnessContractReference.from_dict(payload["terminal_policy_ref"])
            ),
            terminal_policy=(
                None
                if payload["terminal_policy"] is None
                else HarnessTerminalSideEffectPolicy.from_dict(
                    payload["terminal_policy"]
                )
            ),
            checksum=payload["checksum"],
        )


def graph_node_from_dict(value: Mapping[str, Any]) -> HarnessGraphNode:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "graph node must be an object",
            code="invalid_graph_node_contract",
        )
    kind = HarnessGraphNodeKind(value.get("node_kind"))
    if kind == HarnessGraphNodeKind.EXECUTABLE:
        _exact_keys(
            value,
            {
                "node_id",
                "node_kind",
                "step_id",
                "declaration_order",
                "step_ref",
                "worker_ref",
                "activity_ref",
                "gate_refs",
                "side_effect_ref",
                "input_keys",
                "output_keys",
                "metadata",
            },
            "executable node",
        )
        return HarnessExecutableNode(
            node_id=value["node_id"],
            step_id=value["step_id"],
            declaration_order=value["declaration_order"],
            step_ref=HarnessContractReference.from_dict(value["step_ref"]),
            worker_ref=HarnessContractReference.from_dict(value["worker_ref"]),
            activity_ref=HarnessContractReference.from_dict(value["activity_ref"]),
            gate_refs=tuple(
                HarnessContractReference.from_dict(item)
                for item in _array(value["gate_refs"], "node.gate_refs")
            ),
            side_effect_ref=(
                None
                if value["side_effect_ref"] is None
                else HarnessContractReference.from_dict(value["side_effect_ref"])
            ),
            input_keys=tuple(_array(value["input_keys"], "node.input_keys")),
            output_keys=tuple(_array(value["output_keys"], "node.output_keys")),
            metadata=value["metadata"],
        )
    _exact_keys(
        value,
        {
            "node_id",
            "node_kind",
            "declaration_order",
            "branches",
            "join",
            "loop",
            "wait",
            "merge",
            "metadata",
        },
        "control node",
    )
    return HarnessControlNode(
        node_id=value["node_id"],
        node_kind=kind,
        declaration_order=value["declaration_order"],
        branches=tuple(
            HarnessBranch.from_dict(item)
            for item in _array(value["branches"], "node.branches")
        ),
        join=None
        if value["join"] is None
        else HarnessJoinContract.from_dict(value["join"]),
        loop=None
        if value["loop"] is None
        else HarnessLoopContract.from_dict(value["loop"]),
        wait=None
        if value["wait"] is None
        else HarnessWaitContract.from_dict(value["wait"]),
        merge=None
        if value["merge"] is None
        else HarnessMergeContract.from_dict(value["merge"]),
        metadata=value["metadata"],
    )


class HarnessGraphChecksumRegistry:
    def __init__(self) -> None:
        self._by_checksum: dict[str, Any] = {}

    def register(self, graph: NormalizedHarnessGraph) -> None:
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        projection = freeze_json(
            graph.checksum_projection(), "graph.checksum_projection"
        )
        existing = self._by_checksum.get(graph.checksum)
        if existing is not None and existing != projection:
            raise HarnessValidationError(
                "one graph checksum resolved to conflicting canonical content",
                code="graph_checksum_collision",
                details={"checksum": graph.checksum},
            )
        self._by_checksum[graph.checksum] = projection

    def resolve(self, checksum: str) -> dict[str, Any]:
        try:
            projection = self._by_checksum[str(checksum)]
        except KeyError as exc:
            raise HarnessValidationError(
                "normalized graph checksum is not registered",
                code="unknown_graph_checksum",
                details={"checksum": str(checksum)},
            ) from exc
        thawed = thaw_json(projection)
        if not isinstance(thawed, dict):
            raise AssertionError(
                "registered graph projection did not thaw to an object"
            )
        return thawed


def _require_reference_kind(
    value: Any,
    expected: HarnessContractKind,
    field_name: str,
) -> HarnessContractReference:
    if (
        not isinstance(value, HarnessContractReference)
        or value.contract_kind != expected
    ):
        raise HarnessValidationError(
            f"{field_name} must be a {expected.value} contract reference",
            code="invalid_graph_contract_reference",
            details={"field": field_name, "expected_kind": expected.value},
        )
    return value


def _declaration_order(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HarnessValidationError(
            "node declaration_order must be a non-negative integer",
            code="invalid_node_declaration_order",
        )
    return value


def _text_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    result = tuple(required_text(item, field_name) for item in values)
    if not allow_empty and not result:
        raise HarnessValidationError(
            f"{field_name} must not be empty",
            code="empty_graph_contract_field",
            details={"field": field_name},
        )
    return result


def _is_condition(value: Any) -> bool:
    return isinstance(value, ConditionPredicate | ConditionAll | ConditionAny)


def _array(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise HarnessValidationError(
            f"{field_name} must be an array",
            code="invalid_graph_contract",
        )
    return tuple(value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_graph_contract",
        )
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} fields do not match its schema",
            code="invalid_graph_contract",
            details={
                "missing": sorted(expected.difference(actual)),
                "unknown": sorted(str(item) for item in actual.difference(expected)),
            },
        )


__all__ = [
    "HarnessBranch",
    "HarnessCompensationReference",
    "HarnessContractKind",
    "HarnessContractReference",
    "HarnessControlNode",
    "HarnessExecutableNode",
    "HarnessGraphChecksumRegistry",
    "HarnessGraphEdge",
    "HarnessGraphEdgeKind",
    "HarnessGraphNode",
    "HarnessGraphNodeKind",
    "HarnessJoinContract",
    "HarnessLoopContract",
    "HarnessMergeContract",
    "HarnessMergeKind",
    "HarnessWaitContract",
    "NormalizedHarnessGraph",
    "graph_node_from_dict",
]
