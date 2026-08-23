from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphChecksumRegistry,
    HarnessGraphEdge,
    HarnessGraphNodeKind,
    NormalizedHarnessGraph,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_DEFINITION_SCHEMA,
)


def test_normalized_graph_round_trip_and_checksum_are_stable_under_input_permutation() -> (
    None
):
    collect = _executable("collect", 0, worker_version="1")
    finish = HarnessControlNode(
        node_id="finish",
        node_kind=HarnessGraphNodeKind.TERMINAL,
        declaration_order=1,
    )
    edge = HarnessGraphEdge(
        edge_id="collect-to-finish",
        source_id="collect",
        target_id="finish",
        edge_kind="dependency",
    )
    graph = _graph(nodes=(finish, collect), edges=(edge,))
    permuted = _graph(nodes=(collect, finish), edges=(edge,))

    assert graph.checksum == permuted.checksum
    assert graph.to_dict() == permuted.to_dict()
    assert NormalizedHarnessGraph.from_dict(graph.to_dict()) == graph
    assert graph.to_dict()["schema_version"] == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA


def test_exact_contract_versions_participate_in_graph_checksum() -> None:
    graph_v1 = _graph(
        nodes=(
            _executable("collect", 0, worker_version="1"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )
    graph_v2 = _graph(
        nodes=(
            _executable("collect", 0, worker_version="2"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )

    assert graph_v1.checksum != graph_v2.checksum

    with pytest.raises(HarnessValidationError) as captured:
        HarnessContractReference("worker", "research.collect", "latest")
    assert captured.value.code == "graph_inexact_version_reference"


def test_supplied_checksum_mismatch_and_simulated_collision_fail_closed() -> None:
    first = _graph(
        nodes=(
            _executable("collect", 0, worker_version="1"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )
    with pytest.raises(HarnessValidationError) as captured:
        NormalizedHarnessGraph(
            graph_id=first.graph_id,
            graph_version=first.graph_version,
            graph_ref=first.graph_ref,
            definition_schema_version=first.definition_schema_version,
            definition_checksum=first.definition_checksum,
            nodes=first.nodes,
            edges=first.edges,
            entry_node_ids=first.entry_node_ids,
            terminal_node_ids=first.terminal_node_ids,
            input_keys=first.input_keys,
            terminal_output_keys=first.terminal_output_keys,
            terminal_policy_ref=first.terminal_policy_ref,
            terminal_policy=first.terminal_policy,
            checksum="sha256:" + "0" * 64,
        )
    assert captured.value.code == "graph_checksum_mismatch"

    second = _graph(
        nodes=(
            _executable("collect", 0, worker_version="2"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )
    registry = HarnessGraphChecksumRegistry()
    registry.register(first)
    object.__setattr__(second, "checksum", first.checksum)

    with pytest.raises(HarnessValidationError) as captured:
        registry.register(second)
    assert captured.value.code == "graph_checksum_collision"


def test_legacy_normalized_graph_shape_is_rejected_by_live_reader() -> None:
    graph = _graph(
        nodes=(
            _executable("collect", 0, worker_version="1"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )
    payload = graph.to_dict()
    payload["schema_version"] = "newsroom.harness-normalized-graph/v1"
    with pytest.raises(HarnessValidationError) as captured:
        NormalizedHarnessGraph.from_dict(payload)
    assert captured.value.code == "legacy_graph_schema_forbidden"


def test_terminal_policy_handler_and_inherited_gates_participate_in_checksum() -> None:
    base = _graph_with_terminal_policy(_terminal_policy())
    changed_handler = _graph_with_terminal_policy(
        _terminal_policy(handler="publication.commit@3")
    )
    changed_gate = _graph_with_terminal_policy(
        _terminal_policy(inherited_gate_refs=("quality@2",))
    )

    assert base.checksum != changed_handler.checksum
    assert base.checksum != changed_gate.checksum
    assert NormalizedHarnessGraph.from_dict(base.to_dict()) == base


def test_unknown_schema_and_inexact_reference_fail_closed() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        NormalizedHarnessGraph.from_dict(
            {"schema_version": "newsroom.harness-normalized-graph/v999"}
        )
    assert captured.value.code == "legacy_graph_schema_forbidden"

    with pytest.raises(HarnessValidationError):
        _ref(HarnessContractKind.WORKER, "worker", "default")


def _graph(*, nodes, edges) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="research-graph",
        graph_version="1",
        graph_ref=_ref(HarnessContractKind.GRAPH, "research-graph", "1"),
        definition_schema_version=HARNESS_GRAPH_DEFINITION_SCHEMA,
        definition_checksum="sha256:" + "b" * 64,
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_node_ids=("collect",),
        terminal_node_ids=("finish",),
        terminal_policy_ref=_ref(HarnessContractKind.TERMINAL_POLICY, "publication", "4"),
        terminal_policy=_terminal_policy(),
    )


def _graph_with_terminal_policy(
    policy: HarnessTerminalSideEffectPolicy,
) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="research-terminal-graph",
        graph_version="1",
        graph_ref=_ref(HarnessContractKind.GRAPH, "research-terminal-graph", "1"),
        definition_schema_version=HARNESS_GRAPH_DEFINITION_SCHEMA,
        definition_checksum="sha256:" + "c" * 64,
        nodes=(
            _executable("collect", 0, worker_version="1"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
        entry_node_ids=("collect",),
        terminal_node_ids=("finish",),
        terminal_policy_ref=_ref(
            HarnessContractKind.TERMINAL_POLICY,
            policy.policy_id,
            policy.version,
        ),
        terminal_policy=policy,
    )


def _terminal_policy(
    *,
    handler: str = "publication.commit@2",
    inherited_gate_refs: tuple[str, ...] = ("quality@1",),
) -> HarnessTerminalSideEffectPolicy:
    return HarnessTerminalSideEffectPolicy(
        policy_id="publication",
        version="4",
        handler=handler,
        kind="publication",
        requires_approval=False,
        retry_limit=1,
        not_required_evidence_ref="sha256:" + "a" * 64,
        inherited_gate_refs=inherited_gate_refs,
    )


def _executable(
    node_id: str, order: int, *, worker_version: str
) -> HarnessExecutableNode:
    return HarnessExecutableNode(
        node_id=node_id,
        step_id=node_id,
        declaration_order=order,
        step_ref=_ref(HarnessContractKind.STEP, f"research.{node_id}", "1"),
        worker_ref=_ref(
            HarnessContractKind.WORKER, f"research.{node_id}", worker_version
        ),
        activity_ref=_ref(HarnessContractKind.ACTIVITY, "harness.worker", "1"),
        gate_refs=(_ref(HarnessContractKind.GATE, "candidate-schema", "1"),),
        input_keys=("paper",),
        output_keys=("candidate",),
        metadata={"safe": {"parallel": False}},
    )


def _edge() -> HarnessGraphEdge:
    return HarnessGraphEdge(
        edge_id="collect-to-finish",
        source_id="collect",
        target_id="finish",
        edge_kind="dependency",
    )


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    version: str,
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)
