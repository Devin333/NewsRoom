from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.conditions import ConditionPredicate
from framework.harness.graph.dsl import (
    BoundedLoop,
    Choice,
    ChoiceBranch,
    CompensationBinding,
    HarnessGraphSpec,
    ParallelAll,
    ParallelAny,
    ParallelBranch,
    PureMerge,
    Sequence,
    StepRef,
    VerifiedAggregation,
    Wait,
)
from framework.harness.workflow.graph import (
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphEdgeKind,
    HarnessGraphNodeKind,
)
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.graph.activity import HarnessRetryPolicy, HarnessStepSpec


def test_legacy_linear_workflow_lowers_to_dependency_edges_without_fake_control_workers() -> (
    None
):
    workflow = HarnessWorkflowSpec(
        workflow_id="legacy-linear",
        workflow_version="3",
        steps=_steps("collect", "analyze", "report"),
        entry_step_id="collect",
        routing_rules=(
            HarnessRoutingRule("collect", "analyze"),
            HarnessRoutingRule("analyze", "report"),
        ),
    )

    first = HarnessWorkflowGraphCompiler().compile(workflow)
    second = HarnessWorkflowGraphCompiler().compile(workflow)

    assert first.declaration_mode == "legacy"
    assert first.graph == second.graph
    assert first.graph.checksum == second.graph.checksum
    assert [node.node_id for node in first.graph.nodes] == [
        "analyze",
        "collect",
        "report",
    ]
    assert all(isinstance(node, HarnessExecutableNode) for node in first.graph.nodes)
    assert all(node.metadata["worker_type"] == "script" for node in first.graph.nodes)
    assert {
        (edge.source_id, edge.target_id, edge.edge_kind) for edge in first.graph.edges
    } == {
        ("collect", "analyze", HarnessGraphEdgeKind.DEPENDENCY),
        ("analyze", "report", HarnessGraphEdgeKind.DEPENDENCY),
    }
    assert first.graph.entry_node_ids == ("collect",)
    assert first.graph.terminal_node_ids == ("report",)


def test_legacy_conditional_routes_lower_to_one_explicit_choice_with_stable_priority() -> (
    None
):
    workflow = HarnessWorkflowSpec(
        workflow_id="legacy-choice",
        steps=_steps("classify", "accepted", "repair", "finish"),
        entry_step_id="classify",
        routing_rules=(
            HarnessRoutingRule(
                "classify",
                "accepted",
                kind="on_verdict",
                condition={"passed": True, "min_score": 0.8},
            ),
            HarnessRoutingRule(
                "classify",
                "repair",
                kind="on_status",
                condition={"status": "failed"},
            ),
        ),
    )

    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    choice = next(node for node in graph.nodes if node.node_id == "choice:classify")
    assert isinstance(choice, HarnessControlNode)
    assert choice.node_kind == HarnessGraphNodeKind.CHOICE
    assert [(branch.priority, branch.is_default) for branch in choice.branches] == [
        (0, False),
        (1, False),
        (2, True),
    ]
    assert [branch.branch_id for branch in choice.branches] == [
        "legacy:classify:0",
        "legacy:classify:1",
        "legacy:classify:default",
    ]
    assert any(
        edge.source_id == "choice:classify"
        and edge.target_id == "accepted"
        and edge.edge_kind == HarnessGraphEdgeKind.DEFAULT
        for edge in graph.edges
    )


def test_explicit_dsl_lowers_all_control_constructs_and_compensation() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="explicit",
        workflow_version="7",
        steps=_steps(
            "start",
            "left",
            "right",
            "fast",
            "slow",
            "loop_body",
            "loop_exit",
            "loop_exhausted",
            "approved",
            "fallback",
            "publish",
            "retract",
        ),
        entry_step_id="start",
        graph=HarnessGraphSpec(
            graph_id="explicit-graph",
            root=Sequence(
                children=(
                    StepRef("start"),
                    Choice(
                        choice_id="route",
                        branches=(
                            ChoiceBranch(
                                branch_id="parallel-all",
                                child=ParallelAll(
                                    fork_id="all-fork",
                                    join_id="all-join",
                                    branches=(
                                        ParallelBranch(
                                            "left", StepRef("left"), "all.left"
                                        ),
                                        ParallelBranch(
                                            "right", StepRef("right"), "all.right"
                                        ),
                                    ),
                                    merge=PureMerge(
                                        "merge.all@2",
                                        ("left_output", "right_output"),
                                    ),
                                ),
                                priority=0,
                                condition=_passed(),
                            ),
                            ChoiceBranch(
                                branch_id="parallel-any",
                                child=ParallelAny(
                                    fork_id="any-fork",
                                    join_id="any-join",
                                    branches=(
                                        ParallelBranch(
                                            "fast", StepRef("fast"), "any.fast"
                                        ),
                                        ParallelBranch(
                                            "slow", StepRef("slow"), "any.slow"
                                        ),
                                    ),
                                ),
                                priority=1,
                                is_default=True,
                            ),
                        ),
                    ),
                    BoundedLoop(
                        loop_id="bounded-loop",
                        body=StepRef("loop_body"),
                        condition=_passed(),
                        max_iterations=2,
                        exit=StepRef("loop_exit"),
                        exhaustion=StepRef("loop_exhausted"),
                    ),
                    Wait(
                        wait_id="approval",
                        kind="approval",
                        correlation={"run": "graph.inputs.run_id"},
                        signal_type="approval",
                        signal_version="1",
                        tenant_scope_path="graph.inputs.tenant_id",
                        identity_scope_path="graph.inputs.actor_id",
                    ),
                    Choice(
                        choice_id="approval-route",
                        branches=(
                            ChoiceBranch(
                                "approved",
                                StepRef("approved"),
                                0,
                                condition=_passed(),
                            ),
                            ChoiceBranch(
                                "fallback", StepRef("fallback"), 1, is_default=True
                            ),
                        ),
                    ),
                    StepRef("publish"),
                )
            ),
            compensations=(
                CompensationBinding(
                    binding_id="retract",
                    for_node_id="publish",
                    compensation_step_id="retract",
                    handler_ref="publication.retract@1",
                    activity_contract_ref="publication.retract.activity@1",
                ),
            ),
        ),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="publication",
            version="4",
            handler="publication.commit@2",
            kind="publication",
            requires_approval=True,
            retry_limit=1,
        ),
    )

    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    kinds = {node.node_id: node.node_kind for node in graph.nodes}

    assert kinds["route"] == HarnessGraphNodeKind.CHOICE
    assert kinds["route:join"] == HarnessGraphNodeKind.CHOICE_JOIN
    assert kinds["all-fork"] == HarnessGraphNodeKind.FORK_ALL
    assert kinds["all-join"] == HarnessGraphNodeKind.JOIN_ALL
    assert kinds["all-join:merge"] == HarnessGraphNodeKind.MERGE
    assert kinds["any-fork"] == HarnessGraphNodeKind.FORK_ANY
    assert kinds["any-join"] == HarnessGraphNodeKind.JOIN_ANY
    assert kinds["bounded-loop"] == HarnessGraphNodeKind.LOOP_GUARD
    assert kinds["bounded-loop:join"] == HarnessGraphNodeKind.LOOP_JOIN
    assert kinds["approval"] == HarnessGraphNodeKind.WAIT
    assert kinds["compensation:retract"] == HarnessGraphNodeKind.EXECUTABLE
    assert graph.entry_node_ids == ("start",)
    assert graph.terminal_node_ids == ("publish",)
    assert graph.terminal_policy_ref is not None
    assert graph.terminal_policy_ref.exact_ref == "publication@4"
    assert graph.terminal_policy == workflow.terminal_side_effect_policy
    assert graph.terminal_policy.handler_ref.handler_id == "publication.commit"
    assert graph.compensation_refs[0].handler_ref.exact_ref == "publication.retract@1"
    merge = next(node for node in graph.nodes if node.node_id == "all-join:merge")
    assert isinstance(merge, HarnessControlNode)
    assert merge.merge is not None
    assert merge.merge.output_keys == ("left_output", "right_output")
    assert merge.merge.merge_ref is not None
    assert merge.merge.merge_ref.exact_ref == "merge.all@2"
    assert any(edge.edge_kind == HarnessGraphEdgeKind.LOOP_BACK for edge in graph.edges)
    assert any(
        edge.target_id == "route:join"
        and edge.edge_kind == HarnessGraphEdgeKind.DEPENDENCY
        and edge.branch_id is not None
        for edge in graph.edges
    )
    assert any(
        edge.edge_kind == HarnessGraphEdgeKind.COMPENSATION for edge in graph.edges
    )


def test_compiler_retains_retry_repair_and_marks_inferred_legacy_versions() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="repair",
        steps=(
            HarnessStepSpec(
                step_id="call",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(max_retries=2, repair_step_id="repair"),
                quality_gate="candidate_schema",
            ),
            HarnessStepSpec(step_id="repair", worker_type="script"),
        ),
        entry_step_id="call",
    )

    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    call = next(node for node in graph.nodes if node.node_id == "call")

    assert isinstance(call, HarnessExecutableNode)
    assert call.gate_refs[0].exact_ref == "candidate_schema@1"
    assert call.metadata["contract_provenance"]["gate_version_inferred"] is True
    assert call.metadata["retry_policy"]["max_retries"] == 2
    assert any(
        edge.source_id == "call"
        and edge.target_id == "repair"
        and edge.edge_kind == HarnessGraphEdgeKind.REPAIR
        for edge in graph.edges
    )


def test_verified_aggregation_compiles_through_step_lifecycle_and_merge_marker() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="verified-aggregation",
        steps=(
            HarnessStepSpec("left", "script", output_key="left_output"),
            HarnessStepSpec("right", "script", output_key="right_output"),
            HarnessStepSpec(
                "aggregate",
                "script",
                input_keys=("branch_output_refs",),
                output_key="combined",
                quality_gate="aggregate.schema@1",
            ),
        ),
        entry_step_id="left",
        graph=HarnessGraphSpec(
            "aggregation-graph",
            ParallelAll(
                "fork",
                "join",
                (
                    ParallelBranch("left", StepRef("left"), "left"),
                    ParallelBranch("right", StepRef("right"), "right"),
                ),
                merge=VerifiedAggregation(
                    StepRef("aggregate"),
                    "branch_output_refs",
                ),
            ),
        ),
    )

    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    marker = next(node for node in graph.nodes if node.node_id == "join:merge")

    assert isinstance(marker, HarnessControlNode)
    assert marker.merge is not None
    assert marker.merge.merge_kind.value == "aggregation_step"
    assert marker.merge.aggregation_node_id == "aggregate"
    assert marker.merge.output_keys == ("combined",)
    assert graph.terminal_node_ids == ("join:merge",)
    assert {
        (edge.source_id, edge.target_id)
        for edge in graph.edges
        if edge.edge_kind is HarnessGraphEdgeKind.DEPENDENCY
    }.issuperset({("join", "aggregate"), ("aggregate", "join:merge")})


def test_unknown_step_and_loop_without_explicit_exit_fail_closed() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkflowGraphCompiler().compile(
            HarnessWorkflowSpec(
                workflow_id="unknown-step",
                steps=_steps("known"),
                entry_step_id="known",
                graph=HarnessGraphSpec("graph", StepRef("missing")),
            )
        )
    assert captured.value.code == "unknown_graph_step_reference"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkflowGraphCompiler().compile(
            HarnessWorkflowSpec(
                workflow_id="missing-exit",
                steps=_steps("body"),
                entry_step_id="body",
                graph=HarnessGraphSpec(
                    "graph",
                    BoundedLoop("loop", StepRef("body"), _passed(), 1),
                ),
            )
        )
    assert captured.value.code == "loop_exit_missing"


def _steps(*step_ids: str) -> tuple[HarnessStepSpec, ...]:
    return tuple(
        HarnessStepSpec(
            step_id=step_id,
            worker_type="script",
            quality_gate=f"{step_id}.schema@1",
            output_key=f"{step_id}_output",
        )
        for step_id in step_ids
    )


def _passed() -> ConditionPredicate:
    return ConditionPredicate("quality_verdict.passed", "equals", True)
