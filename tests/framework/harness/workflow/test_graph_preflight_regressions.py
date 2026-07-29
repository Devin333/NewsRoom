from __future__ import annotations

from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.workflow.conditions import ConditionPredicate
from framework.harness.workflow.dsl import (
    BoundedLoop,
    HarnessGraphSpec,
    ParallelAll,
    ParallelBranch,
    Sequence,
    StepRef,
    Wait,
)
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdge,
    HarnessLoopContract,
    NormalizedHarnessGraph,
)
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec
from framework.harness.workflow.validation import (
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
    HarnessGraphRegistrySnapshot,
    graph_contract_references,
)


def test_wait_scope_and_correlation_sources_must_be_structural_graph_paths() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="invalid-wait-scope",
        steps=(HarnessStepSpec("unused", "script"),),
        entry_step_id="unused",
        graph=HarnessGraphSpec(
            graph_id="invalid-wait-scope",
            root=Wait(
                wait_id="approval",
                kind="approval",
                correlation={"subject": "worker_result.output.subject"},
                signal_type="approval",
                signal_version="1",
                tenant_scope_path="worker_result.output.tenant",
                identity_scope_path="secrets.actor",
            ),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    diagnostics = HarnessGraphPreflight().validate(
        graph,
        registry=_snapshot(graph),
    ).diagnostics
    codes = {item.code for item in diagnostics}

    assert "invalid_wait_correlation_source" in codes
    assert "invalid_wait_tenant_scope_path" in codes
    assert "invalid_wait_identity_scope_path" in codes


def test_only_declared_loop_terminal_may_use_loop_back_edge() -> None:
    body = _node("body", 1)
    exit_node = _node("exit", 2)
    loop = HarnessControlNode(
        node_id="loop",
        node_kind="loop_guard",
        declaration_order=0,
        loop=HarnessLoopContract(
            body_entry_node_ids=("body",),
            body_terminal_node_ids=("body",),
            condition=_passed(),
            max_iterations=2,
            exit_node_ids=("exit",),
        ),
    )
    graph = _normalized(
        nodes=(loop, body, exit_node),
        edges=(
            HarnessGraphEdge("loop-body", "loop", "body", "loop_body", loop_id="loop"),
            HarnessGraphEdge("body-back", "body", "loop", "loop_back", loop_id="loop"),
            HarnessGraphEdge("loop-exit", "loop", "exit", "loop_exit", loop_id="loop"),
            HarnessGraphEdge("forged-back", "exit", "loop", "loop_back", loop_id="loop"),
        ),
        entry=("loop",),
        terminal=("exit",),
    )

    codes = {item.code for item in _validate(graph).diagnostics}

    assert "invalid_loop_back_edge" in codes
    assert "undeclared_graph_cycle" in codes


def test_repair_and_compensation_edges_cannot_prove_a_forward_terminal_path() -> None:
    for edge_kind in ("repair", "compensation"):
        entry = _node("entry", 0)
        auxiliary = _node("auxiliary", 1)
        terminal = _node("terminal", 2)
        graph = _normalized(
            nodes=(entry, auxiliary, terminal),
            edges=(
                HarnessGraphEdge(
                    f"entry-{edge_kind}",
                    "entry",
                    "auxiliary",
                    edge_kind,
                ),
                HarnessGraphEdge(
                    "auxiliary-terminal",
                    "auxiliary",
                    "terminal",
                    "dependency",
                ),
            ),
            entry=("entry",),
            terminal=("terminal",),
        )

        codes = {item.code for item in _validate(graph).diagnostics}

        assert "entry_without_terminal_path" in codes
        assert f"unbound_{edge_kind}_edge" in codes


def test_parallel_duplicate_output_keys_require_explicit_merge_without_metadata_hint() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="parallel-duplicate-output",
        steps=(
            HarnessStepSpec("left", "script", output_key="shared"),
            HarnessStepSpec("right", "script", output_key="shared"),
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id="parallel-duplicate-output",
            root=ParallelAll(
                fork_id="fork",
                join_id="join",
                branches=(
                    ParallelBranch("left", StepRef("left"), "branch.left"),
                    ParallelBranch("right", StepRef("right"), "branch.right"),
                ),
            ),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    codes = {item.code for item in _validate(graph).diagnostics}

    assert "parallel_shared_write_conflict" in codes


def test_parallel_all_join_makes_every_unique_branch_output_available() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="parallel-all-dataflow",
        steps=(
            HarnessStepSpec("left", "script", output_key="left_result"),
            HarnessStepSpec("right", "script", output_key="right_result"),
            HarnessStepSpec(
                "aggregate",
                "script",
                input_keys=("left_result", "right_result"),
                output_key="report",
            ),
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            graph_id="parallel-all-dataflow",
            root=Sequence(
                (
                    ParallelAll(
                        fork_id="fork",
                        join_id="join",
                        branches=(
                            ParallelBranch("left", StepRef("left"), "branch.left"),
                            ParallelBranch("right", StepRef("right"), "branch.right"),
                        ),
                    ),
                    StepRef("aggregate"),
                )
            ),
            terminal_output_keys=("report",),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    diagnostics = _validate(graph).diagnostics

    assert not [
        item
        for item in diagnostics
        if item.code == "unreachable_input_producer" and item.node_id == "aggregate"
    ]


def test_activation_bound_counts_every_node_in_each_loop_iteration() -> None:
    body_ids = tuple(f"body-{index}" for index in range(5))
    workflow = HarnessWorkflowSpec(
        workflow_id="long-loop",
        steps=tuple(
            HarnessStepSpec(step_id, "script") for step_id in (*body_ids, "exit")
        ),
        entry_step_id=body_ids[0],
        graph=HarnessGraphSpec(
            graph_id="long-loop",
            root=BoundedLoop(
                loop_id="loop",
                body=Sequence(tuple(StepRef(step_id) for step_id in body_ids)),
                condition=_passed(),
                max_iterations=10,
                exit=StepRef("exit"),
            ),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    result = HarnessGraphPreflight(
        policy=HarnessGraphPreflightPolicy(max_node_activations=51)
    ).validate(graph, registry=_snapshot(graph))
    diagnostic = next(
        item for item in result.diagnostics if item.code == "graph_activation_limit_exceeded"
    )

    assert diagnostic.details["actual"] == 52


def test_legacy_unconditional_jump_does_not_leave_dead_nodes_in_normalized_graph() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="legacy-jump",
        steps=(
            HarnessStepSpec("start", "script"),
            HarnessStepSpec("skipped", "script"),
            HarnessStepSpec("finish", "script"),
        ),
        entry_step_id="start",
        routing_rules=(HarnessRoutingRule("start", "finish"),),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    result = _validate(graph)

    assert result.is_valid
    assert {node.node_id for node in graph.nodes} == {"start", "finish"}


def test_legacy_first_unconditional_rule_truncates_later_routes() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="legacy-first-match",
        steps=(
            HarnessStepSpec("start", "script"),
            HarnessStepSpec("first", "script"),
            HarnessStepSpec("later", "script"),
            HarnessStepSpec("finish", "script"),
        ),
        entry_step_id="start",
        routing_rules=(
            HarnessRoutingRule("start", "first"),
            HarnessRoutingRule(
                "start",
                "later",
                kind="on_status",
                condition={"status": "failed"},
            ),
            HarnessRoutingRule("first", "finish"),
            HarnessRoutingRule("later", "finish"),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    assert _validate(graph).is_valid
    assert "choice:start" not in {node.node_id for node in graph.nodes}
    assert {node.node_id for node in graph.nodes} == {"start", "first", "finish"}
    assert any(
        edge.source_id == "start"
        and edge.target_id == "first"
        and edge.edge_kind.value == "dependency"
        for edge in graph.edges
    )


def test_legacy_rules_after_first_unconditional_rule_are_not_choice_branches() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="legacy-conditional-first-match",
        steps=(
            HarnessStepSpec("start", "script"),
            HarnessStepSpec("fallback", "script"),
            HarnessStepSpec("failed", "script"),
            HarnessStepSpec("unreachable", "script"),
            HarnessStepSpec("finish", "script"),
        ),
        entry_step_id="start",
        routing_rules=(
            HarnessRoutingRule(
                "start",
                "failed",
                kind="on_status",
                condition={"status": "failed"},
            ),
            HarnessRoutingRule("start", "fallback"),
            HarnessRoutingRule(
                "start",
                "unreachable",
                kind="on_status",
                condition={"status": "succeeded"},
            ),
            HarnessRoutingRule("fallback", "finish"),
            HarnessRoutingRule("failed", "finish"),
            HarnessRoutingRule("unreachable", "finish"),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    choice = next(node for node in graph.nodes if node.node_id == "choice:start")

    assert isinstance(choice, HarnessControlNode)
    assert _validate(graph).is_valid
    assert [branch.entry_node_ids for branch in choice.branches] == [
        ("failed",),
        ("fallback",),
    ]
    assert "unreachable" not in {node.node_id for node in graph.nodes}


def _validate(graph: NormalizedHarnessGraph):
    return HarnessGraphPreflight().validate(graph, registry=_snapshot(graph))


def _snapshot(graph: NormalizedHarnessGraph) -> HarnessGraphRegistrySnapshot:
    return HarnessGraphRegistrySnapshot(
        graph_contract_references(graph),
        parallel_safe_activity_refs=tuple(
            node.activity_ref.exact_ref
            for node in graph.nodes
            if isinstance(node, HarnessExecutableNode)
        ),
    )


def _normalized(
    *,
    nodes: tuple[HarnessExecutableNode | HarnessControlNode, ...],
    edges: tuple[HarnessGraphEdge, ...],
    entry: tuple[str, ...],
    terminal: tuple[str, ...],
) -> NormalizedHarnessGraph:
    return NormalizedHarnessGraph(
        graph_id="manual",
        workflow_id="manual",
        workflow_version="1",
        workflow_ref=_ref(HarnessContractKind.WORKFLOW, "manual", "1"),
        nodes=nodes,
        edges=edges,
        entry_node_ids=entry,
        terminal_node_ids=terminal,
    )


def _node(node_id: str, order: int) -> HarnessExecutableNode:
    return HarnessExecutableNode(
        node_id=node_id,
        step_id=node_id,
        declaration_order=order,
        step_ref=_ref(HarnessContractKind.STEP, node_id, "1"),
        worker_ref=_ref(HarnessContractKind.WORKER, "script", "1"),
        activity_ref=_ref(HarnessContractKind.ACTIVITY, "activity", "1"),
    )


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    version: str,
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)


def _passed() -> ConditionPredicate:
    return ConditionPredicate("quality_verdict.passed", "equals", True)
