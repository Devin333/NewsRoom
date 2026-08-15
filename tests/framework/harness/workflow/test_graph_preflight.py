from __future__ import annotations

from time import perf_counter

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.conditions import ConditionPredicate
from framework.harness.graph.dsl import (
    BoundedLoop,
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    PureMerge,
    Sequence,
    StepRef,
)
from framework.harness.graph.model import (
    HarnessBranch,
    HarnessCompensationReference,
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdge,
    HarnessJoinContract,
    HarnessLoopContract,
    HarnessWaitContract,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessStepSpec
from framework.harness.graph.validation import (
    HarnessGraphPreflightPolicy,
    HarnessGraphRegistrySnapshot,
    graph_contract_references,
)
from framework.harness.workflow.validation import HarnessGraphPreflight


def test_valid_sequence_graph_passes_every_preflight_phase() -> None:
    prepared = _valid_prepared()

    assert prepared.is_valid
    assert prepared.validation.diagnostics == ()
    assert prepared.require_valid() == prepared.graph
    assert prepared.graph.input_keys == ("paper",)
    assert prepared.graph.terminal_output_keys == ("report",)


def test_control_fact_declaration_requires_exact_deterministic_gate() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="control-facts",
        steps=(
            HarnessStepSpec(
                "classify",
                "llm",
                metadata={"control_fact_paths": ("classification",)},
            ),
        ),
        entry_step_id="classify",
        graph=HarnessGraphSpec("control-facts", StepRef("classify")),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    codes = {item.code for item in _preflight(graph).diagnostics}

    assert "control_fact_gate_missing" in codes


def test_structural_validation_reports_duplicate_endpoint_reachability_and_cycle_errors() -> (
    None
):
    one = _node("one", 0)
    duplicate = _node("one", 1)
    unreachable = _node("unreachable", 2)
    graph = _normalized(
        nodes=(one, duplicate, unreachable),
        edges=(
            HarnessGraphEdge("bad-target", "one", "missing", "dependency"),
            HarnessGraphEdge("self-cycle", "one", "one", "dependency"),
        ),
        entry=("one",),
        terminal=("unreachable",),
    )

    result = _preflight(graph)
    codes = {item.code for item in result.diagnostics}

    assert "duplicate_node_id" in codes
    assert "unknown_edge_target" in codes
    assert "unreachable_node" in codes
    assert "unreachable_terminal" in codes
    assert "entry_without_terminal_path" in codes
    assert "undeclared_graph_cycle" in codes
    with pytest.raises(HarnessValidationError) as captured:
        result.raise_if_invalid()
    assert captured.value.code == "harness_graph_preflight_failed"


def test_semantic_validation_rejects_choice_loop_wait_and_compensation_ambiguity() -> (
    None
):
    target = _node("target", 4)
    choice = HarnessControlNode(
        node_id="choice",
        node_kind="choice",
        declaration_order=0,
        branches=(
            HarnessBranch("a", ("target",), ("target",), 0, "a", is_default=True),
            HarnessBranch("b", ("target",), ("target",), 0, "b", is_default=True),
        ),
    )
    loop = HarnessControlNode(
        node_id="loop",
        node_kind="loop_guard",
        declaration_order=1,
        loop=HarnessLoopContract(
            body_entry_node_ids=("target",),
            body_terminal_node_ids=("target",),
            condition=_passed(),
            max_iterations=0,
            exit_node_ids=("target",),
        ),
    )
    wait = HarnessControlNode(
        node_id="timer",
        node_kind="wait",
        declaration_order=2,
        wait=HarnessWaitContract(
            wait_id="timer",
            kind="timer",
            correlation={"key": "value"},
            signal_type="timer",
            signal_version="1",
            tenant_scope_path="graph.inputs.tenant",
            identity_scope_path="graph.inputs.actor",
        ),
    )
    graph = _normalized(
        nodes=(choice, loop, wait, target),
        edges=(
            HarnessGraphEdge(
                "choice-target", "choice", "target", "default", branch_id="a"
            ),
            HarnessGraphEdge("target-loop", "target", "loop", "dependency"),
            HarnessGraphEdge("loop-wait", "loop", "timer", "loop_exit", loop_id="loop"),
        ),
        entry=("choice",),
        terminal=("timer",),
    )

    result = _preflight(graph)
    codes = {item.code for item in result.diagnostics}

    assert "duplicate_choice_priority" in codes
    assert "multiple_choice_defaults" in codes
    assert "invalid_loop_bound" in codes
    assert "timer_deadline_missing" in codes


def test_structural_validation_requires_exact_fork_join_pairing() -> None:
    branch = _node("branch", 1)
    fork = HarnessControlNode(
        "fork",
        "fork_all",
        0,
        branches=(HarnessBranch("a", ("branch",), ("branch",), 0, "a"),),
    )
    join = HarnessControlNode(
        "join",
        "join_all",
        2,
        join=HarnessJoinContract(
            fork_node_id="fork",
            required_branch_ids=("different",),
            failure_policy="fail_fast",
        ),
    )
    graph = _normalized(
        nodes=(fork, branch, join),
        edges=(
            HarnessGraphEdge(
                "fork-branch", "fork", "branch", "fork_branch", branch_id="a"
            ),
            HarnessGraphEdge("branch-join", "branch", "join", "join", branch_id="a"),
        ),
        entry=("fork",),
        terminal=("join",),
    )

    codes = {item.code for item in _preflight(graph).diagnostics}

    assert "fork_join_branch_mismatch" in codes


def test_declared_bounded_loop_is_the_only_cycle_accepted_by_structure() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="valid-loop",
        steps=(HarnessStepSpec("body", "script"), HarnessStepSpec("exit", "script")),
        entry_step_id="body",
        graph=HarnessGraphSpec(
            graph_id="valid-loop",
            root=BoundedLoop(
                loop_id="loop",
                body=StepRef("body"),
                condition=_passed(),
                max_iterations=2,
                exit=StepRef("exit"),
            ),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    codes = {item.code for item in _preflight(graph).diagnostics}

    assert "undeclared_graph_cycle" not in codes


def test_compensation_requires_effectful_origin_instance_scope_and_safe_registry() -> (
    None
):
    origin = _node("origin", 0)
    compensation = _node("compensation", 1)
    reference = HarnessCompensationReference(
        binding_id="undo",
        for_node_id="origin",
        compensation_node_id="compensation",
        handler_ref=_ref("compensation", "undo.handler", "1"),
        activity_ref=_ref("activity", "undo.activity", "1"),
        scope="run",
    )
    graph = NormalizedHarnessGraph(
        graph_id="compensation",
        workflow_id="manual",
        workflow_version="1",
        workflow_ref=_ref("workflow", "manual", "1"),
        nodes=(origin, compensation),
        edges=(
            HarnessGraphEdge("undo-edge", "origin", "compensation", "compensation"),
        ),
        entry_node_ids=("origin",),
        terminal_node_ids=("origin",),
        compensation_refs=(reference,),
    )
    registry = HarnessGraphRegistrySnapshot(graph_contract_references(graph))

    result = HarnessGraphPreflight().validate(graph, registry=registry)
    codes = {item.code for item in result.diagnostics}

    assert "compensation_origin_not_effectful" in codes
    assert "unsupported_compensation_scope" in codes
    assert "compensation_activity_safety_unproven" in codes


def test_dataflow_requires_producer_on_every_path_and_terminal_outputs() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="dataflow",
        steps=(
            HarnessStepSpec("start", "script", output_key="candidate"),
            HarnessStepSpec(
                "finish",
                "script",
                input_keys=("candidate", "missing"),
                output_key="other",
            ),
        ),
        entry_step_id="start",
        graph=HarnessGraphSpec(
            graph_id="dataflow",
            root=Sequence((StepRef("start"), StepRef("finish"))),
            terminal_output_keys=("report",),
        ),
    )
    compiled = HarnessWorkflowGraphCompiler().compile(workflow).graph

    result = _preflight(compiled)
    diagnostics = {item.code: item for item in result.diagnostics}

    assert diagnostics["unreachable_input_producer"].node_id == "finish"
    assert diagnostics["unreachable_input_producer"].details["missing_input_keys"] == (
        "missing",
    )
    assert diagnostics["terminal_output_unavailable"].node_id == "finish"


def test_parallel_shared_write_requires_explicit_merge_and_isolated_namespaces() -> (
    None
):
    def workflow(merge_ref: str | None) -> HarnessWorkflowSpec:
        return HarnessWorkflowSpec(
            workflow_id=f"parallel-{merge_ref}",
            steps=(
                HarnessStepSpec(
                    "left",
                    "script",
                    output_key="shared",
                    metadata={"shared_output_keys": ["shared"]},
                ),
                HarnessStepSpec(
                    "right",
                    "script",
                    output_key="shared",
                    metadata={"shared_output_keys": ["shared"]},
                ),
            ),
            entry_step_id="left",
            graph=HarnessGraphSpec(
                graph_id="parallel",
                root=ParallelAll(
                    fork_id="fork",
                    join_id="join",
                    branches=(
                        ParallelBranch("left", StepRef("left"), "branch.left"),
                        ParallelBranch("right", StepRef("right"), "branch.right"),
                    ),
                    merge=(
                        None
                        if merge_ref is None
                        else PureMerge(merge_ref, ("shared",))
                    ),
                ),
            ),
        )

    without_merge = HarnessWorkflowGraphCompiler().compile(workflow(None)).graph
    with_merge = (
        HarnessWorkflowGraphCompiler().compile(workflow("shared.merge@1")).graph
    )

    assert "parallel_shared_write_conflict" in {
        item.code for item in _preflight(without_merge).diagnostics
    }
    assert "parallel_shared_write_conflict" not in {
        item.code for item in _preflight(with_merge).diagnostics
    }

    incomplete_merge = HarnessWorkflowGraphCompiler().compile(
        HarnessWorkflowSpec(
            workflow_id="parallel-incomplete-merge",
            steps=workflow(None).steps,
            entry_step_id="left",
            graph=HarnessGraphSpec(
                graph_id="parallel-incomplete-merge",
                root=ParallelAll(
                    fork_id="fork",
                    join_id="join",
                    branches=(
                        ParallelBranch("left", StepRef("left"), "branch.left"),
                        ParallelBranch("right", StepRef("right"), "branch.right"),
                    ),
                    merge=PureMerge("shared.merge@1", ("other",)),
                ),
            ),
        )
    ).graph

    assert "parallel_shared_write_unmerged" in {
        item.code for item in _preflight(incomplete_merge).diagnostics
    }


def test_registry_requires_every_exact_reference_and_parallel_safety_capability() -> (
    None
):
    workflow = HarnessWorkflowSpec(
        workflow_id="parallel-registry",
        steps=(HarnessStepSpec("left", "script"), HarnessStepSpec("right", "script")),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id="parallel",
            root=ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("left", StepRef("left"), "left"),
                    ParallelBranch("right", StepRef("right"), "right"),
                ),
            ),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    empty = HarnessGraphRegistrySnapshot(())
    policy = HarnessGraphPreflightPolicy(max_parallelism=2, max_active_nodes=2)

    result = HarnessGraphPreflight(policy=policy).validate(graph, registry=empty)
    codes = [item.code for item in result.diagnostics]

    assert "unresolved_graph_contract_reference" in codes
    assert codes.count("parallel_activity_safety_unproven") == 2

    refs = graph_contract_references(graph)
    activity_refs = tuple(
        node.activity_ref.exact_ref
        for node in graph.nodes
        if isinstance(node, HarnessExecutableNode)
    )
    valid = HarnessGraphPreflight(policy=policy).validate(
        graph,
        registry=HarnessGraphRegistrySnapshot(
            refs,
            parallel_safe_activity_refs=activity_refs,
        ),
    )
    assert valid.is_valid


def test_policy_enforces_size_depth_activation_and_parallel_capacity() -> None:
    graph = _valid_prepared().graph
    policy = HarnessGraphPreflightPolicy(
        max_nodes=1,
        max_edges=1,
        max_depth=1,
        max_node_activations=1,
        max_parallelism=2,
        max_active_nodes=1,
    )

    result = HarnessGraphPreflight(policy=policy).validate(
        graph,
        registry=_snapshot(graph),
    )
    codes = {item.code for item in result.diagnostics}

    assert "graph_node_limit_exceeded" in codes
    assert "graph_depth_limit_exceeded" in codes
    assert "graph_activation_limit_exceeded" in codes
    assert "parallelism_exceeds_active_node_limit" in codes


def test_preflight_benchmark_fixture_handles_1000_nodes_and_5000_edges() -> None:
    graph = _large_dag(node_count=1_000, edge_count=5_000)
    policy = HarnessGraphPreflightPolicy(
        max_nodes=1_000,
        max_edges=5_000,
        max_depth=1_000,
        max_node_activations=1_000,
        max_diagnostics=10,
    )
    started = perf_counter()

    result = HarnessGraphPreflight(policy=policy).validate(
        graph,
        registry=_snapshot(graph),
    )
    elapsed = perf_counter() - started

    assert result.is_valid
    assert len(graph.nodes) == 1_000
    assert len(graph.edges) == 5_000
    assert elapsed < 5.0


def _valid_prepared():
    workflow = HarnessWorkflowSpec(
        workflow_id="valid",
        steps=(
            HarnessStepSpec(
                "collect",
                "script",
                input_keys=("paper",),
                output_key="evidence",
                quality_gate="evidence.schema@1",
            ),
            HarnessStepSpec(
                "report",
                "llm",
                input_keys=("evidence",),
                output_key="report",
                quality_gate="report.schema@1",
            ),
        ),
        entry_step_id="collect",
        graph=HarnessGraphSpec(
            graph_id="valid",
            root=Sequence((StepRef("collect"), StepRef("report"))),
            input_keys=("paper",),
            terminal_output_keys=("report",),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    return HarnessGraphPreflight().prepare(workflow, registry=_snapshot(graph))


def _preflight(graph: NormalizedHarnessGraph):
    return HarnessGraphPreflight().validate(graph, registry=_snapshot(graph))


def _snapshot(graph: NormalizedHarnessGraph) -> HarnessGraphRegistrySnapshot:
    return HarnessGraphRegistrySnapshot(
        graph_contract_references(graph),
        parallel_safe_activity_refs=tuple(
            node.activity_ref.exact_ref
            for node in graph.nodes
            if isinstance(node, HarnessExecutableNode)
        ),
        compensation_safe_activity_refs=tuple(
            reference.activity_ref.exact_ref for reference in graph.compensation_refs
        ),
    )


def _normalized(*, nodes, edges, entry, terminal) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="manual",
        workflow_id="manual",
        workflow_version="1",
        workflow_ref=_ref("workflow", "manual", "1"),
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_node_ids=tuple(entry),
        terminal_node_ids=tuple(terminal),
    )


def _node(node_id: str, order: int) -> HarnessExecutableNode:
    return HarnessExecutableNode(
        node_id=node_id,
        step_id=node_id,
        declaration_order=order,
        step_ref=_ref("step", "manual.step", "1"),
        worker_ref=_ref("worker", "manual.worker", "1"),
        activity_ref=_ref("activity", "manual.activity", "1"),
    )


def _ref(kind: HarnessContractKind | str, contract_id: str, version: str):
    return HarnessContractReference(kind, contract_id, version)


def _passed() -> ConditionPredicate:
    return ConditionPredicate("quality_verdict.passed", "equals", True)


def _large_dag(*, node_count: int, edge_count: int) -> NormalizedHarnessGraph:
    nodes = tuple(_node(f"node-{index:04d}", index) for index in range(node_count))
    pairs: list[tuple[int, int]] = []
    for source in range(node_count - 1):
        pairs.append((source, source + 1))
    distance = 2
    while len(pairs) < edge_count:
        for source in range(node_count - distance):
            pairs.append((source, source + distance))
            if len(pairs) == edge_count:
                break
        distance += 1
    edges = tuple(
        HarnessGraphEdge(
            edge_id=f"edge-{index:05d}",
            source_id=f"node-{source:04d}",
            target_id=f"node-{target:04d}",
            edge_kind="dependency",
        )
        for index, (source, target) in enumerate(pairs)
    )
    return _normalized(
        nodes=nodes,
        edges=edges,
        entry=("node-0000",),
        terminal=(f"node-{node_count - 1:04d}",),
    )
