from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Self

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessExecutableNode,
    NormalizedHarnessGraph,
)
from framework.harness.graph.versioning import (
    GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA,
    GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_DEFINITION_SCHEMA,
    HARNESS_GRAPH_EVENT_SCHEMAS,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*\Z")
_EXACT_SCHEMA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*/v[1-9][0-9]*\Z")
_EXACT_REFERENCE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/+-]*@[A-Za-z0-9][A-Za-z0-9._+-]*\Z"
)
_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})
_MAX_EXECUTION_VERSION_ENTRIES = 10_000
_MAX_EXECUTION_VERSION_TEXT_LENGTH = 512
_TASK_PLAN_SUPPORT_REFERENCE_FIELDS = (
    "candidate_builder_ref",
    "capability_registry_ref",
    "gate_registry_ref",
    "aggregator_ref",
    "checkpoint_ref",
    "result_store_ref",
)
_TASK_PLAN_SUPPORT_FIELDS = frozenset(
    (*_TASK_PLAN_SUPPORT_REFERENCE_FIELDS, "event_schema")
)


@dataclass(frozen=True, slots=True)
class GraphExecutionNodeVersion:
    """Exact execution contracts selected for one executable Graph node."""

    node_id: str
    step_ref: HarnessContractReference | Mapping[str, Any]
    worker_ref: HarnessContractReference | Mapping[str, Any]
    activity_ref: HarnessContractReference | Mapping[str, Any]
    gate_refs: tuple[HarnessContractReference | Mapping[str, Any], ...] = ()
    side_effect_ref: HarnessContractReference | Mapping[str, Any] | None = None
    task_plan_policy_ref: str | None = None
    task_plan_schema: str | None = None
    task_plan_support_refs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        object.__setattr__(
            self,
            "step_ref",
            _contract_reference(
                self.step_ref,
                expected_kind=HarnessContractKind.STEP,
                field_name="step_ref",
            ),
        )
        object.__setattr__(
            self,
            "worker_ref",
            _contract_reference(
                self.worker_ref,
                expected_kind=HarnessContractKind.WORKER,
                field_name="worker_ref",
            ),
        )
        object.__setattr__(
            self,
            "activity_ref",
            _contract_reference(
                self.activity_ref,
                expected_kind=HarnessContractKind.ACTIVITY,
                field_name="activity_ref",
            ),
        )
        raw_gates = tuple(self.gate_refs)
        if len(raw_gates) > _MAX_EXECUTION_VERSION_ENTRIES:
            _invalid("Graph execution node has too many gate references")
        gates = tuple(
            _contract_reference(
                value,
                expected_kind=HarnessContractKind.GATE,
                field_name="gate_refs",
            )
            for value in raw_gates
        )
        if len(gates) != len(set(gates)):
            _invalid("Graph execution node contains duplicate gate references")
        object.__setattr__(
            self,
            "gate_refs",
            tuple(sorted(gates, key=lambda item: item.exact_ref)),
        )
        side_effect = self.side_effect_ref
        if side_effect is not None:
            side_effect = _contract_reference(
                side_effect,
                expected_kind=HarnessContractKind.SIDE_EFFECT,
                field_name="side_effect_ref",
            )
        object.__setattr__(self, "side_effect_ref", side_effect)
        policy_ref, schema, support_refs = _task_plan_contracts(
            self.task_plan_policy_ref,
            self.task_plan_schema,
            self.task_plan_support_refs,
        )
        object.__setattr__(self, "task_plan_policy_ref", policy_ref)
        object.__setattr__(self, "task_plan_schema", schema)
        object.__setattr__(self, "task_plan_support_refs", support_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "step_ref": self.step_ref.to_dict(),
            "worker_ref": self.worker_ref.to_dict(),
            "activity_ref": self.activity_ref.to_dict(),
            "gate_refs": [reference.to_dict() for reference in self.gate_refs],
            "side_effect_ref": (
                None if self.side_effect_ref is None else self.side_effect_ref.to_dict()
            ),
            "task_plan_policy_ref": self.task_plan_policy_ref,
            "task_plan_schema": self.task_plan_schema,
            "task_plan_support_refs": dict(self.task_plan_support_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "node_id",
                "step_ref",
                "worker_ref",
                "activity_ref",
                "gate_refs",
                "side_effect_ref",
                "task_plan_policy_ref",
                "task_plan_schema",
                "task_plan_support_refs",
            },
            "Graph execution node version",
        )
        gate_values = _mapping_sequence(payload["gate_refs"], "gate_refs")
        side_effect = payload["side_effect_ref"]
        if side_effect is not None and not isinstance(side_effect, Mapping):
            _invalid("Graph execution side-effect reference must be an object")
        support = payload["task_plan_support_refs"]
        if not isinstance(support, Mapping):
            _invalid("Graph execution TaskPlan support refs must be an object")
        return cls(
            node_id=payload["node_id"],
            step_ref=_mapping(payload["step_ref"], "step_ref"),
            worker_ref=_mapping(payload["worker_ref"], "worker_ref"),
            activity_ref=_mapping(payload["activity_ref"], "activity_ref"),
            gate_refs=tuple(gate_values),
            side_effect_ref=side_effect,
            task_plan_policy_ref=payload["task_plan_policy_ref"],
            task_plan_schema=payload["task_plan_schema"],
            task_plan_support_refs=support,
        )


@dataclass(frozen=True, slots=True)
class GraphTerminalPolicyVersion:
    """Exact side-effect policy lineage held by a Graph terminal manifest."""

    policy_ref: HarnessContractReference | Mapping[str, Any]
    handler_ref: str
    policy_schema_version: str
    gate_refs: tuple[HarnessContractReference | Mapping[str, Any], ...] = ()
    failure_record_schema: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_ref",
            _contract_reference(
                self.policy_ref,
                expected_kind=HarnessContractKind.TERMINAL_POLICY,
                field_name="policy_ref",
            ),
        )
        object.__setattr__(
            self,
            "handler_ref",
            _exact_reference(self.handler_ref, "handler_ref"),
        )
        object.__setattr__(
            self,
            "policy_schema_version",
            _exact_schema(self.policy_schema_version, "policy_schema_version"),
        )
        raw_gates = tuple(self.gate_refs)
        if len(raw_gates) > _MAX_EXECUTION_VERSION_ENTRIES:
            _invalid("Graph terminal policy has too many gate references")
        gates = tuple(
            _contract_reference(
                value,
                expected_kind=HarnessContractKind.GATE,
                field_name="gate_refs",
            )
            for value in raw_gates
        )
        if len(gates) != len(set(gates)):
            _invalid("Graph terminal policy contains duplicate gate references")
        object.__setattr__(
            self,
            "gate_refs",
            tuple(sorted(gates, key=lambda item: item.exact_ref)),
        )
        failure_schema = self.failure_record_schema
        if failure_schema is not None:
            failure_schema = _exact_schema(
                failure_schema,
                "failure_record_schema",
            )
        object.__setattr__(self, "failure_record_schema", failure_schema)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_ref": self.policy_ref.to_dict(),
            "handler_ref": self.handler_ref,
            "policy_schema_version": self.policy_schema_version,
            "gate_refs": [reference.to_dict() for reference in self.gate_refs],
            "failure_record_schema": self.failure_record_schema,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "policy_ref",
                "handler_ref",
                "policy_schema_version",
                "gate_refs",
                "failure_record_schema",
            },
            "Graph terminal policy version",
        )
        return cls(
            policy_ref=_mapping(payload["policy_ref"], "policy_ref"),
            handler_ref=payload["handler_ref"],
            policy_schema_version=payload["policy_schema_version"],
            gate_refs=tuple(_mapping_sequence(payload["gate_refs"], "gate_refs")),
            failure_record_schema=payload["failure_record_schema"],
        )


@dataclass(frozen=True, slots=True)
class GraphExecutionVersionManifest:
    """Immutable version lineage for a Graph-only terminal execution record.

    The contract is intentionally data-only. It does not resolve a worker, invoke
    a gate, or authorize terminal publication; the Artifact owner consumes it as
    inactive v2 manifest evidence until a Gate B writer is installed.
    """

    graph_id: str
    graph_version: str
    graph_ref: HarnessContractReference | Mapping[str, Any]
    definition_schema_version: str
    definition_checksum: str
    normalized_graph_schema_version: str
    normalized_graph_checksum: str
    compiler_version: str
    condition_policy_version: str
    state_schema_version: str
    decision_schema_version: str
    checkpoint_schema_version: str
    event_schema_versions: Mapping[str, str]
    terminal_node_ids: tuple[str, ...]
    node_versions: tuple[GraphExecutionNodeVersion | Mapping[str, Any], ...]
    terminal_policy: GraphTerminalPolicyVersion | Mapping[str, Any]
    terminal_failure_policy: GraphTerminalPolicyVersion | Mapping[str, Any] | None
    schema_version: str = GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA
    execution_manifest_checksum: str | None = None

    def __post_init__(self) -> None:
        graph_id = _identifier(self.graph_id, "graph_id")
        graph_version = _exact_version(self.graph_version, "graph_version")
        graph_ref = _contract_reference(
            self.graph_ref,
            expected_kind=HarnessContractKind.GRAPH,
            field_name="graph_ref",
        )
        if graph_ref.contract_id != graph_id or graph_ref.version != graph_version:
            _invalid("Graph execution manifest graph_ref does not match identity")
        definition_schema = _exact_schema(
            self.definition_schema_version,
            "definition_schema_version",
        )
        if definition_schema != HARNESS_GRAPH_DEFINITION_SCHEMA:
            _invalid("Graph execution manifest definition schema is unsupported")
        normalized_schema = _exact_schema(
            self.normalized_graph_schema_version,
            "normalized_graph_schema_version",
        )
        if normalized_schema != GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            _invalid("Graph execution manifest normalized schema is unsupported")
        compiler_version = _exact_schema(
            self.compiler_version,
            "compiler_version",
        )
        if compiler_version != HARNESS_GRAPH_ONLY_COMPILER_VERSION:
            _invalid("Graph execution manifest compiler version is unsupported")
        condition_policy_version = _exact_schema(
            self.condition_policy_version,
            "condition_policy_version",
        )
        if condition_policy_version != HARNESS_CONDITION_POLICY_VERSION:
            _invalid("Graph execution manifest condition policy is unsupported")
        state_schema_version = _exact_schema(
            self.state_schema_version,
            "state_schema_version",
        )
        if state_schema_version != GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA:
            _invalid("Graph execution manifest state schema is unsupported")
        decision_schema_version = _exact_schema(
            self.decision_schema_version,
            "decision_schema_version",
        )
        if decision_schema_version != GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA:
            _invalid("Graph execution manifest decision schema is unsupported")
        checkpoint_schema_version = _exact_schema(
            self.checkpoint_schema_version,
            "checkpoint_schema_version",
        )
        if checkpoint_schema_version != GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA:
            _invalid("Graph execution manifest checkpoint schema is unsupported")
        event_schema_versions = _event_schema_versions(
            self.event_schema_versions
        )
        terminal_node_ids = _stable_identifiers(
            self.terminal_node_ids,
            "terminal_node_ids",
            allow_empty=False,
        )
        node_versions = tuple(
            value
            if isinstance(value, GraphExecutionNodeVersion)
            else GraphExecutionNodeVersion.from_dict(_mapping(value, "node_versions"))
            for value in self.node_versions
        )
        if not node_versions:
            _invalid("Graph execution manifest requires executable node versions")
        if len(node_versions) > _MAX_EXECUTION_VERSION_ENTRIES:
            _invalid("Graph execution manifest has too many node versions")
        node_versions = tuple(sorted(node_versions, key=lambda item: item.node_id))
        if len({item.node_id for item in node_versions}) != len(node_versions):
            _invalid("Graph execution manifest contains duplicate node versions")
        terminal_policy = _terminal_policy(self.terminal_policy, "terminal_policy")
        if terminal_policy.failure_record_schema is not None:
            _invalid("successful terminal policy cannot carry a failure record schema")
        failure_policy = self.terminal_failure_policy
        if failure_policy is not None:
            failure_policy = _terminal_policy(
                failure_policy,
                "terminal_failure_policy",
            )
            if failure_policy.failure_record_schema is None:
                _invalid("terminal failure policy requires its failure record schema")
            if failure_policy.policy_ref == terminal_policy.policy_ref:
                _invalid("terminal policy cannot share failure policy identity")
            if failure_policy.handler_ref == terminal_policy.handler_ref:
                _invalid("terminal policy cannot share failure handler identity")
        if self.schema_version != GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA:
            _invalid("unsupported Graph execution version manifest schema")
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "graph_version", graph_version)
        object.__setattr__(self, "graph_ref", graph_ref)
        object.__setattr__(self, "definition_schema_version", definition_schema)
        object.__setattr__(
            self,
            "definition_checksum",
            _checksum(self.definition_checksum, "definition_checksum"),
        )
        object.__setattr__(
            self,
            "normalized_graph_schema_version",
            normalized_schema,
        )
        object.__setattr__(
            self,
            "normalized_graph_checksum",
            _checksum(self.normalized_graph_checksum, "normalized_graph_checksum"),
        )
        object.__setattr__(self, "compiler_version", compiler_version)
        object.__setattr__(
            self,
            "condition_policy_version",
            condition_policy_version,
        )
        object.__setattr__(self, "state_schema_version", state_schema_version)
        object.__setattr__(self, "decision_schema_version", decision_schema_version)
        object.__setattr__(
            self,
            "checkpoint_schema_version",
            checkpoint_schema_version,
        )
        object.__setattr__(self, "event_schema_versions", event_schema_versions)
        object.__setattr__(self, "terminal_node_ids", terminal_node_ids)
        object.__setattr__(self, "node_versions", node_versions)
        object.__setattr__(self, "terminal_policy", terminal_policy)
        object.__setattr__(self, "terminal_failure_policy", failure_policy)
        expected = canonical_checksum(self.checksum_projection())
        supplied = self.execution_manifest_checksum
        if supplied is not None and _checksum(
            supplied,
            "execution_manifest_checksum",
        ) != expected:
            raise HarnessValidationError(
                "Graph execution version manifest checksum does not match "
                "canonical content",
                code="graph_execution_version_manifest_checksum_mismatch",
            )
        object.__setattr__(self, "execution_manifest_checksum", expected)

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref.to_dict(),
            "definition_schema_version": self.definition_schema_version,
            "definition_checksum": self.definition_checksum,
            "normalized_graph_schema_version": self.normalized_graph_schema_version,
            "normalized_graph_checksum": self.normalized_graph_checksum,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "state_schema_version": self.state_schema_version,
            "decision_schema_version": self.decision_schema_version,
            "checkpoint_schema_version": self.checkpoint_schema_version,
            "event_schema_versions": dict(self.event_schema_versions),
            "terminal_node_ids": list(self.terminal_node_ids),
            "node_versions": [item.to_dict() for item in self.node_versions],
            "terminal_policy": self.terminal_policy.to_dict(),
            "terminal_failure_policy": (
                None
                if self.terminal_failure_policy is None
                else self.terminal_failure_policy.to_dict()
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "execution_manifest_checksum": self.execution_manifest_checksum,
        }

    def verify_integrity(self) -> None:
        if self.execution_manifest_checksum != canonical_checksum(
            self.checksum_projection()
        ):
            raise HarnessValidationError(
                "Graph execution version manifest checksum does not match "
                "canonical content",
                code="graph_execution_version_manifest_checksum_mismatch",
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_id",
                "graph_version",
                "graph_ref",
                "definition_schema_version",
                "definition_checksum",
                "normalized_graph_schema_version",
                "normalized_graph_checksum",
                "compiler_version",
                "condition_policy_version",
                "state_schema_version",
                "decision_schema_version",
                "checkpoint_schema_version",
                "event_schema_versions",
                "terminal_node_ids",
                "node_versions",
                "terminal_policy",
                "terminal_failure_policy",
                "execution_manifest_checksum",
            },
            "Graph execution version manifest",
        )
        if payload["schema_version"] != GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA:
            raise HarnessValidationError(
                "unsupported Graph execution version manifest schema",
                code="unsupported_graph_execution_version_manifest_schema",
                details={"schema_version": str(payload["schema_version"])},
            )
        failure_policy = payload["terminal_failure_policy"]
        if failure_policy is not None and not isinstance(failure_policy, Mapping):
            _invalid("Graph terminal failure policy must be an object")
        execution_manifest_checksum = _checksum(
            payload["execution_manifest_checksum"],
            "execution_manifest_checksum",
        )
        return cls(
            graph_id=payload["graph_id"],
            graph_version=payload["graph_version"],
            graph_ref=_mapping(payload["graph_ref"], "graph_ref"),
            definition_schema_version=payload["definition_schema_version"],
            definition_checksum=payload["definition_checksum"],
            normalized_graph_schema_version=payload[
                "normalized_graph_schema_version"
            ],
            normalized_graph_checksum=payload["normalized_graph_checksum"],
            compiler_version=payload["compiler_version"],
            condition_policy_version=payload["condition_policy_version"],
            state_schema_version=payload["state_schema_version"],
            decision_schema_version=payload["decision_schema_version"],
            checkpoint_schema_version=payload["checkpoint_schema_version"],
            event_schema_versions=_mapping(
                payload["event_schema_versions"],
                "event_schema_versions",
            ),
            terminal_node_ids=tuple(
                _text_sequence(payload["terminal_node_ids"], "terminal_node_ids")
            ),
            node_versions=tuple(
                GraphExecutionNodeVersion.from_dict(item)
                for item in _mapping_sequence(payload["node_versions"], "node_versions")
            ),
            terminal_policy=GraphTerminalPolicyVersion.from_dict(
                _mapping(payload["terminal_policy"], "terminal_policy")
            ),
            terminal_failure_policy=(
                None
                if failure_policy is None
                else GraphTerminalPolicyVersion.from_dict(failure_policy)
            ),
            schema_version=payload["schema_version"],
            execution_manifest_checksum=execution_manifest_checksum,
        )

    @classmethod
    def from_normalized_graph(cls, graph: NormalizedHarnessGraph) -> Self:
        """Project exact Graph-only execution versions without runtime authority."""

        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        if graph.schema_version != GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            raise HarnessValidationError(
                "Graph execution version manifests require a Graph-only normalized "
                "graph",
                code="graph_execution_version_manifest_schema_mismatch",
                details={"schema_version": graph.schema_version},
            )
        if (
            graph.workflow_id is not None
            or graph.workflow_version is not None
            or graph.workflow_ref is not None
        ):
            raise HarnessValidationError(
                "Graph execution version manifest rejects legacy orchestration "
                "identity aliases",
                code="legacy_graph_identity_forbidden",
            )
        if graph.checksum != canonical_checksum(graph.checksum_projection()):
            raise HarnessValidationError(
                "normalized Graph checksum does not match canonical content",
                code="graph_checksum_mismatch",
            )
        if graph.graph_ref is None or graph.definition_checksum is None:
            raise HarnessValidationError(
                "Graph-only normalized graph lacks execution lineage",
                code="graph_execution_version_manifest_lineage_missing",
            )
        if graph.terminal_policy is None or graph.terminal_policy_ref is None:
            raise HarnessValidationError(
                "Graph-only normalized graph lacks its terminal side-effect policy",
                code="graph_execution_version_manifest_terminal_policy_missing",
            )
        return cls(
            graph_id=graph.graph_id,
            graph_version=graph.graph_version or "",
            graph_ref=graph.graph_ref,
            definition_schema_version=graph.definition_schema_version or "",
            definition_checksum=graph.definition_checksum,
            normalized_graph_schema_version=graph.schema_version,
            normalized_graph_checksum=graph.checksum or "",
            compiler_version=graph.compiler_version,
            condition_policy_version=graph.condition_policy_version,
            state_schema_version=GRAPH_ONLY_HARNESS_GRAPH_STATE_SCHEMA,
            decision_schema_version=GRAPH_ONLY_HARNESS_GRAPH_DECISION_SCHEMA,
            checkpoint_schema_version=GRAPH_ONLY_HARNESS_GRAPH_CHECKPOINT_SCHEMA,
            event_schema_versions=HARNESS_GRAPH_EVENT_SCHEMAS,
            terminal_node_ids=graph.terminal_node_ids,
            node_versions=tuple(
                _node_version(node)
                for node in graph.nodes
                if isinstance(node, HarnessExecutableNode)
            ),
            terminal_policy=_policy_version(
                graph.terminal_policy_ref,
                graph.terminal_policy,
                failure=False,
            ),
            terminal_failure_policy=(
                None
                if graph.terminal_failure_policy is None
                or graph.terminal_failure_policy_ref is None
                else _policy_version(
                    graph.terminal_failure_policy_ref,
                    graph.terminal_failure_policy,
                    failure=True,
                )
            ),
        )


def _node_version(node: HarnessExecutableNode) -> GraphExecutionNodeVersion:
    metadata = node.metadata
    worker_type = metadata.get("worker_type")
    task_plan_policy_ref: str | None = None
    task_plan_schema: str | None = None
    task_plan_support_refs: Mapping[str, str] = {}
    if worker_type == "task_plan":
        step_metadata = metadata.get("step_metadata")
        if not isinstance(step_metadata, Mapping):
            _invalid("Graph TaskPlan execution node lacks step metadata")
        task_plan_policy_ref = step_metadata.get("task_plan_policy_ref")
        task_plan_schema = step_metadata.get("task_plan_schema")
        support = step_metadata.get("task_plan_support")
        if not isinstance(support, Mapping):
            _invalid("Graph TaskPlan execution node lacks support refs")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in support.items()
        ):
            _invalid("Graph TaskPlan execution node support refs must be strings")
        task_plan_support_refs = dict(support)
    return GraphExecutionNodeVersion(
        node_id=node.node_id,
        step_ref=node.step_ref,
        worker_ref=node.worker_ref,
        activity_ref=node.activity_ref,
        gate_refs=node.gate_refs,
        side_effect_ref=node.side_effect_ref,
        task_plan_policy_ref=task_plan_policy_ref,
        task_plan_schema=task_plan_schema,
        task_plan_support_refs=task_plan_support_refs,
    )


def _policy_version(
    policy_ref: HarnessContractReference,
    policy: Any,
    *,
    failure: bool,
) -> GraphTerminalPolicyVersion:
    gate_refs: tuple[HarnessContractReference, ...] = ()
    if not failure:
        gate_refs = tuple(
            _gate_reference(value, "terminal_policy.inherited_gate_refs")
            for value in policy.inherited_gate_refs
        )
    return GraphTerminalPolicyVersion(
        policy_ref=policy_ref,
        handler_ref=str(policy.handler_ref),
        policy_schema_version=policy.schema_version,
        gate_refs=gate_refs,
        failure_record_schema=(
            policy.failure_record_schema if failure else None
        ),
    )


def _event_schema_versions(value: Mapping[str, str]) -> Mapping[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != set(HARNESS_GRAPH_EVENT_SCHEMAS)
    ):
        _invalid(
            "Graph execution event schemas are incomplete or contain unknown fields"
        )
    normalized: dict[str, str] = {}
    for event_type, expected_schema in HARNESS_GRAPH_EVENT_SCHEMAS.items():
        _identifier(event_type, f"event_schema_versions.{event_type}")
        schema = _exact_schema(
            value[event_type],
            f"event_schema_versions.{event_type}",
        )
        if schema != expected_schema:
            _invalid("Graph execution event schema is unsupported")
        normalized[event_type] = schema
    return MappingProxyType(dict(sorted(normalized.items())))


def _task_plan_contracts(
    policy_ref: str | None,
    schema: str | None,
    support_refs: Mapping[str, str],
) -> tuple[str | None, str | None, Mapping[str, str]]:
    if policy_ref is None:
        if schema is not None or support_refs:
            _invalid("non-TaskPlan node cannot carry TaskPlan execution contracts")
        return None, None, {}
    policy_ref = _exact_reference(policy_ref, "task_plan_policy_ref")
    schema = _exact_schema(schema, "task_plan_schema")
    if not isinstance(support_refs, Mapping) or any(
        not isinstance(key, str) for key in support_refs
    ):
        _invalid("TaskPlan support refs must be a string-keyed object")
    if frozenset(support_refs) != _TASK_PLAN_SUPPORT_FIELDS:
        _invalid("TaskPlan support refs are incomplete or contain unknown fields")
    normalized: dict[str, str] = {}
    for field_name in _TASK_PLAN_SUPPORT_REFERENCE_FIELDS:
        normalized[field_name] = _exact_reference(
            support_refs[field_name],
            f"task_plan_support_refs.{field_name}",
        )
    normalized["event_schema"] = _exact_schema(
        support_refs["event_schema"],
        "task_plan_support_refs.event_schema",
    )
    return policy_ref, schema, MappingProxyType(dict(sorted(normalized.items())))


def _terminal_policy(
    value: GraphTerminalPolicyVersion | Mapping[str, Any],
    field_name: str,
) -> GraphTerminalPolicyVersion:
    if isinstance(value, GraphTerminalPolicyVersion):
        return value
    return GraphTerminalPolicyVersion.from_dict(_mapping(value, field_name))


def _contract_reference(
    value: HarnessContractReference | Mapping[str, Any],
    *,
    expected_kind: HarnessContractKind,
    field_name: str,
) -> HarnessContractReference:
    reference = (
        value
        if isinstance(value, HarnessContractReference)
        else HarnessContractReference.from_dict(_mapping(value, field_name))
    )
    if reference.contract_kind is not expected_kind:
        _invalid(
            f"{field_name} must be an exact {expected_kind.value} contract reference"
        )
    _exact_version(reference.version, field_name)
    return reference


def _gate_reference(value: Any, field_name: str) -> HarnessContractReference:
    text = _exact_reference(value, field_name)
    contract_id, version = text.rsplit("@", maxsplit=1)
    return HarnessContractReference(HarnessContractKind.GATE, contract_id, version)


def _stable_identifiers(
    values: Sequence[Any],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    raw_values = _text_sequence(values, field_name)
    if len(raw_values) > _MAX_EXECUTION_VERSION_ENTRIES:
        _invalid(f"{field_name} has too many entries")
    normalized = tuple(_identifier(value, field_name) for value in raw_values)
    if (not allow_empty and not normalized) or len(normalized) != len(set(normalized)):
        _invalid(f"{field_name} must contain unique values")
    return tuple(sorted(normalized))


def _exact_mapping(
    value: Mapping[str, Any],
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    payload = _mapping(value, model)
    if set(payload) != expected:
        _invalid(f"{model} fields are invalid")
    return payload


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _invalid(f"{field_name} must be an object")
    return dict(value)


def _mapping_sequence(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _invalid(f"{field_name} must be an array")
    if len(value) > _MAX_EXECUTION_VERSION_ENTRIES:
        _invalid(f"{field_name} has too many entries")
    return tuple(_mapping(item, field_name) for item in value)


def _text_sequence(value: Any, field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        _invalid(f"{field_name} must be an array")
    return tuple(value)


def _identifier(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_EXECUTION_VERSION_TEXT_LENGTH
    ):
        _invalid(f"{field_name} must be a non-blank identifier")
    if _IDENTIFIER.fullmatch(value) is None:
        _invalid(f"{field_name} is invalid")
    return value


def _exact_version(value: Any, field_name: str) -> str:
    version = _identifier(value, field_name)
    if version.casefold() in _MOVING_VERSIONS:
        _invalid(f"{field_name} must not use a moving version")
    return version


def _exact_schema(value: Any, field_name: str) -> str:
    schema = _identifier(value, field_name)
    if _EXACT_SCHEMA.fullmatch(schema) is None:
        _invalid(f"{field_name} must be an exact versioned schema")
    return schema


def _exact_reference(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_EXECUTION_VERSION_TEXT_LENGTH
    ):
        _invalid(f"{field_name} must be an exact contract reference")
    if _EXACT_REFERENCE.fullmatch(value) is None:
        _invalid(f"{field_name} must be an exact contract reference")
    version = value.rsplit("@", maxsplit=1)[1]
    if version.casefold() in _MOVING_VERSIONS:
        _invalid(f"{field_name} must not use a moving version")
    return value


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM.fullmatch(value) is None:
        _invalid(f"{field_name} must be a sha256 checksum")
    return value


def _invalid(message: str) -> None:
    raise HarnessValidationError(
        message,
        code="invalid_graph_execution_version_manifest",
    )


__all__ = [
    "GRAPH_EXECUTION_VERSION_MANIFEST_SCHEMA",
    "GraphExecutionNodeVersion",
    "GraphExecutionVersionManifest",
    "GraphTerminalPolicyVersion",
]
