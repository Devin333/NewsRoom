from __future__ import annotations

import json
from pathlib import Path

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
    HARNESS_GRAPH_DSL_SCHEMA,
    HARNESS_GRAPH_EVENT_SCHEMAS,
    HARNESS_GRAPH_INSPECTION_SCHEMA,
    HARNESS_GRAPH_RUNTIME_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    LEGACY_STATE_SCHEMA,
    HarnessGraphContractKind,
)


_SCHEMA_REGISTRY_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "harness"
    / "schema_version_registry_v2.json"
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
    assert graph.to_dict()["schema_version"] == NORMALIZED_HARNESS_GRAPH_SCHEMA


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
            workflow_id=first.workflow_id,
            workflow_version=first.workflow_version,
            workflow_ref=first.workflow_ref,
            nodes=first.nodes,
            edges=first.edges,
            entry_node_ids=first.entry_node_ids,
            terminal_node_ids=first.terminal_node_ids,
            input_keys=first.input_keys,
            terminal_output_keys=first.terminal_output_keys,
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


def test_legacy_normalized_graph_shape_is_verified_before_bounded_upcast() -> None:
    graph = _graph(
        nodes=(
            _executable("collect", 0, worker_version="1"),
            HarnessControlNode("finish", "terminal", 1),
        ),
        edges=(_edge(),),
    )
    payload = graph.to_dict()
    payload.pop("input_keys")
    payload.pop("terminal_output_keys")
    payload.pop("terminal_policy")
    payload["checksum"] = canonical_checksum(
        {key: value for key, value in payload.items() if key != "checksum"}
    )

    restored = NormalizedHarnessGraph.from_dict(payload)

    assert restored.input_keys == ()
    assert restored.terminal_output_keys == ()
    assert restored.terminal_policy is None
    assert restored.checksum != payload["checksum"]


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


def test_schema_registry_reads_legacy_but_never_executes_it() -> None:
    registry = DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY

    state_registration = registry.require_readable(
        HarnessGraphContractKind.GRAPH_STATE,
        LEGACY_STATE_SCHEMA,
    )
    assert LEGACY_STATE_SCHEMA in state_registration.legacy_upcast_sources
    with pytest.raises(HarnessValidationError) as captured:
        registry.require_executable(
            HarnessGraphContractKind.GRAPH_STATE, LEGACY_STATE_SCHEMA
        )
    assert captured.value.code == "graph_schema_not_executable"

    graph_registration = registry.require_executable(
        HarnessGraphContractKind.NORMALIZED_GRAPH,
        NORMALIZED_HARNESS_GRAPH_SCHEMA,
    )
    assert graph_registration.writer_schema == NORMALIZED_HARNESS_GRAPH_SCHEMA
    assert registry.to_dict()["runtime_version"] == HARNESS_GRAPH_RUNTIME_VERSION
    assert (
        registry.registration_for("graph_dsl").writer_schema == HARNESS_GRAPH_DSL_SCHEMA
    )


def test_code_schema_registry_matches_locked_contract_fixture() -> None:
    evidence = json.loads(_SCHEMA_REGISTRY_FIXTURE.read_text(encoding="utf-8"))

    assert evidence["runtime_generation"] == HARNESS_GRAPH_RUNTIME_VERSION
    assert evidence["contract_schemas"] == {
        "graph_dsl": HARNESS_GRAPH_DSL_SCHEMA,
        "normalized_graph": NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "graph_state": DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.registration_for(
            "graph_state"
        ).writer_schema,
        "graph_decision": DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.registration_for(
            "graph_decision"
        ).writer_schema,
        "graph_checkpoint": DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.registration_for(
            "graph_checkpoint"
        ).writer_schema,
        "graph_inspection": HARNESS_GRAPH_INSPECTION_SCHEMA,
    }
    assert {
        item["event_type"]: item["data_schema"] for item in evidence["graph_events"]
    } == dict(HARNESS_GRAPH_EVENT_SCHEMAS)
    assert DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.registration_for(
        "graph_event"
    ).writer_schemas == tuple(HARNESS_GRAPH_EVENT_SCHEMAS.values())


def test_unknown_schema_and_inexact_reference_fail_closed() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY.require_readable(
            HarnessGraphContractKind.NORMALIZED_GRAPH,
            "newsroom.normalized-harness-graph/v999",
        )
    assert captured.value.code == "unsupported_graph_schema"

    with pytest.raises(HarnessValidationError):
        _ref(HarnessContractKind.WORKER, "worker", "default")


def _graph(*, nodes, edges) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="research-graph",
        workflow_id="research",
        workflow_version="1",
        workflow_ref=_ref(HarnessContractKind.WORKFLOW, "research", "1"),
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_node_ids=("collect",),
        terminal_node_ids=("finish",),
    )


def _graph_with_terminal_policy(
    policy: HarnessTerminalSideEffectPolicy,
) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="research-terminal-graph",
        workflow_id="research",
        workflow_version="1",
        workflow_ref=_ref(HarnessContractKind.WORKFLOW, "research", "1"),
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
