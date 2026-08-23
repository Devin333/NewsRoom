from __future__ import annotations

from dataclasses import replace

import pytest

from business.research.graphs import (
    RESEARCH_DYNAMIC_STAGE_ID,
    build_dynamic_paper_analysis_graph_definition,
    build_paper_analysis_graph_definition,
    build_reader_repair_graph_definition,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import (
    BoundedLoop,
    Choice,
    ChoiceBranch,
    CompensationBinding,
    ConditionPredicate,
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    HarnessContractKind,
    HarnessContractReference,
    HarnessExecutableNode,
    HarnessGraphCompileResult,
    HarnessGraphCompiler,
    HarnessGraphDefinition,
    HarnessGraphEdgeKind,
    HarnessGraphLeafBinding,
    HarnessGraphNodeKind,
    HarnessGraphPreflight,
    HarnessGraphSpec,
    HarnessLeafActivityKind,
    HarnessStepSpec,
    HarnessWorkerType,
    NormalizedHarnessGraph,
    ParallelAll,
    ParallelAny,
    ParallelBranch,
    PureMerge,
    Sequence,
    StepRef,
    Wait,
)
from framework.harness.side_effects.models import HarnessTerminalSideEffectPolicy


def test_graph_compiler_emits_v2_identity_without_workflow_aliases() -> None:
    definition = build_paper_analysis_graph_definition()

    first = HarnessGraphCompiler().compile(definition)
    second = HarnessGraphCompiler().compile(definition)
    payload = first.graph.to_dict()

    assert first == second
    assert first.compiler_version == HARNESS_GRAPH_ONLY_COMPILER_VERSION
    assert first.definition_checksum == definition.definition_checksum
    assert first.graph.schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
    assert first.graph.graph_id == definition.graph_id
    assert first.graph.graph_version == definition.graph_version
    assert first.graph.graph_ref is not None
    assert first.graph.graph_ref.contract_kind is HarnessContractKind.GRAPH
    assert first.graph.graph_ref.exact_ref == (
        f"{definition.graph_id}@{definition.graph_version}"
    )
    assert not {"workflow_id", "workflow_version", "workflow_ref"}.intersection(
        payload
    )
    assert "declaration_mode" not in first.to_dict()
    assert NormalizedHarnessGraph.from_dict(payload) == first.graph

    executable_nodes = tuple(
        node
        for node in first.graph.nodes
        if isinstance(node, HarnessExecutableNode)
    )
    assert executable_nodes
    for node in executable_nodes:
        assert node.step_ref.contract_id == f"{definition.graph_id}:{node.step_id}"
        assert node.step_ref.version == definition.graph_version
        assert node.metadata["binding_source"] == "graph_definition"


def test_graph_compiler_uses_task_plan_stage_binding_as_only_authority() -> None:
    definition = build_dynamic_paper_analysis_graph_definition()

    graph = HarnessGraphCompiler().compile(definition).graph
    node = next(
        item
        for item in graph.nodes
        if isinstance(item, HarnessExecutableNode)
        and item.step_id == RESEARCH_DYNAMIC_STAGE_ID
    )
    binding = definition.task_plan_stage_binding(RESEARCH_DYNAMIC_STAGE_ID)
    assert binding is not None
    metadata = node.metadata["step_metadata"]

    assert node.worker_ref == binding.worker_ref
    assert node.activity_ref == binding.activity_ref
    assert metadata["dynamic_stage"] is True
    assert metadata["task_plan_policy_ref"] == binding.policy_ref
    assert metadata["task_plan_schema"] == binding.task_plan_schema
    assert tuple(metadata["required_output_roles"]) == binding.required_output_roles
    assert dict(metadata["task_plan_support"]) == dict(binding.support_refs)
    assert HarnessGraphPreflight().validate_static(graph).is_valid


def test_graph_compiler_lowers_all_explicit_control_constructs() -> None:
    definition = _control_construct_definition()

    graph = HarnessGraphCompiler().compile(definition).graph
    kinds = {node.node_id: node.node_kind for node in graph.nodes}

    assert kinds["route"] is HarnessGraphNodeKind.CHOICE
    assert kinds["route:join"] is HarnessGraphNodeKind.CHOICE_JOIN
    assert kinds["all-fork"] is HarnessGraphNodeKind.FORK_ALL
    assert kinds["all-join"] is HarnessGraphNodeKind.JOIN_ALL
    assert kinds["all-join:merge"] is HarnessGraphNodeKind.MERGE
    assert kinds["any-fork"] is HarnessGraphNodeKind.FORK_ANY
    assert kinds["any-join"] is HarnessGraphNodeKind.JOIN_ANY
    assert kinds["bounded-loop"] is HarnessGraphNodeKind.LOOP_GUARD
    assert kinds["bounded-loop:join"] is HarnessGraphNodeKind.LOOP_JOIN
    assert kinds["approval"] is HarnessGraphNodeKind.WAIT
    assert kinds["compensation:retract"] is HarnessGraphNodeKind.EXECUTABLE
    assert graph.entry_node_ids == ("start",)
    assert graph.terminal_node_ids == ("publish",)
    assert any(
        edge.edge_kind is HarnessGraphEdgeKind.LOOP_BACK for edge in graph.edges
    )
    assert any(
        edge.edge_kind is HarnessGraphEdgeKind.COMPENSATION for edge in graph.edges
    )
    assert HarnessGraphPreflight().validate_static(graph).is_valid


def test_graph_compiler_pins_repair_output_and_failure_policy_lineage() -> None:
    definition = build_reader_repair_graph_definition()

    result = HarnessGraphCompiler().compile(definition)
    graph = result.graph

    assert HarnessGraphPreflight().validate_static(graph).is_valid
    assert len(graph.committed_output_refs) == 1
    committed = graph.committed_output_refs[0]
    source_binding = definition.committed_output_bindings[0]
    assert committed.binding_id == source_binding.binding_id
    assert committed.producer_node_id == source_binding.producer_node_id
    assert committed.consumer_node_id == source_binding.consumer_node_id
    assert committed.receipt_input_key == source_binding.receipt_input_key
    assert committed.producer_activity_ref.contract_kind is HarnessContractKind.ACTIVITY
    assert committed.consumer_activity_ref.contract_kind is HarnessContractKind.ACTIVITY

    assert len(graph.repair_refs) == len(definition.repair_bindings)
    assert {reference.binding_id for reference in graph.repair_refs} == {
        binding.binding_id for binding in definition.repair_bindings
    }
    assert all(reference.triggers for reference in graph.repair_refs)
    assert graph.terminal_failure_policy == (
        definition.terminal_failure_side_effect_policy
    )
    assert graph.terminal_failure_policy_ref is not None
    assert graph.terminal_failure_policy_ref.exact_ref == (
        definition.terminal_failure_side_effect_policy.reference
    )


def test_graph_only_preflight_never_falls_back_to_legacy_repair_authority() -> None:
    graph = HarnessGraphCompiler().compile(build_reader_repair_graph_definition()).graph
    tampered = replace(graph, repair_refs=(), checksum=None)

    result = HarnessGraphPreflight().validate_static(tampered)

    assert not result.is_valid
    assert "unbound_repair_edge" in {
        diagnostic.code for diagnostic in result.diagnostics
    }


def test_graph_only_preflight_validates_committed_output_lineage() -> None:
    graph = HarnessGraphCompiler().compile(build_reader_repair_graph_definition()).graph
    reference = graph.committed_output_refs[0]
    tampered_reference = replace(
        reference,
        producer_activity_ref=reference.consumer_activity_ref,
        receipt_input_key=reference.producer_output_key,
    )
    tampered = replace(
        graph,
        committed_output_refs=(tampered_reference,),
        checksum=None,
    )

    result = HarnessGraphPreflight().validate_static(tampered)
    codes = {diagnostic.code for diagnostic in result.diagnostics}

    assert not result.is_valid
    assert "committed_output_producer_activity_mismatch" in codes
    assert "committed_output_receipt_input_collision" in codes


def test_graph_only_preflight_rejects_duplicate_repair_authority() -> None:
    graph = HarnessGraphCompiler().compile(build_reader_repair_graph_definition()).graph
    tampered = replace(
        graph,
        repair_refs=(*graph.repair_refs, graph.repair_refs[0]),
        checksum=None,
    )

    result = HarnessGraphPreflight().validate_static(tampered)

    assert not result.is_valid
    assert "duplicate_graph_repair_reference" in {
        diagnostic.code for diagnostic in result.diagnostics
    }


def test_graph_only_normalized_graph_requires_terminal_policy_snapshots() -> None:
    graph = HarnessGraphCompiler().compile(build_reader_repair_graph_definition()).graph

    with pytest.raises(HarnessValidationError) as terminal_error:
        replace(graph, terminal_policy=None, checksum=None)
    assert terminal_error.value.code == "graph_terminal_policy_snapshot_missing"

    with pytest.raises(HarnessValidationError) as failure_error:
        replace(graph, terminal_failure_policy=None, checksum=None)
    assert (
        failure_error.value.code
        == "graph_terminal_failure_policy_snapshot_missing"
    )


def test_graph_compiler_rejects_task_plan_authority_in_activity_metadata() -> None:
    definition = build_dynamic_paper_analysis_graph_definition()
    activities = tuple(
        replace(
            activity,
            metadata={"task_plan_policy_ref": "attacker.policy@9"},
        )
        if activity.step_id == RESEARCH_DYNAMIC_STAGE_ID
        else activity
        for activity in definition.activities
    )
    tampered = replace(
        definition,
        activities=activities,
        definition_checksum=None,
    )

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphCompiler().compile(tampered)

    assert raised.value.code == "graph_task_plan_authority_metadata_forbidden"


def test_graph_compiler_does_not_infer_gate_or_leaf_versions_from_metadata() -> None:
    definition = build_paper_analysis_graph_definition()
    first = definition.activities[0]
    exact_binding = definition.leaf_activity_binding(first.step_id)
    assert exact_binding is not None
    metadata_only = replace(
        first,
        metadata={
            "worker_id": "attacker.worker",
            "worker_version": "latest",
            "activity_contract_version": "attacker.activity@9",
        },
    )
    metadata_definition = replace(
        definition,
        activities=(metadata_only, *definition.activities[1:]),
        definition_checksum=None,
    )

    graph = HarnessGraphCompiler().compile(metadata_definition).graph
    node = next(
        item
        for item in graph.nodes
        if isinstance(item, HarnessExecutableNode) and item.step_id == first.step_id
    )
    assert node.worker_ref == exact_binding.worker_ref
    assert node.activity_ref == exact_binding.activity_ref

    inexact_gate = replace(first, quality_gate="PaperSourceLineageGate")
    inexact_definition = replace(
        definition,
        activities=(inexact_gate, *definition.activities[1:]),
        definition_checksum=None,
    )
    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphCompiler().compile(inexact_definition)
    assert raised.value.code == "graph_inexact_version_reference"


def test_graph_compile_result_rejects_version_or_definition_substitution() -> None:
    result = HarnessGraphCompiler().compile(build_paper_analysis_graph_definition())

    with pytest.raises(HarnessValidationError) as version_error:
        HarnessGraphCompileResult(
            graph=result.graph,
            definition_checksum=result.definition_checksum,
            compiler_version="newsroom.harness-graph-compiler/v999",
        )
    assert version_error.value.code == "unsupported_graph_compiler"

    with pytest.raises(HarnessValidationError) as lineage_error:
        HarnessGraphCompileResult(
            graph=result.graph,
            definition_checksum="sha256:" + "0" * 64,
        )
    assert lineage_error.value.code == "graph_definition_lineage_mismatch"


def test_graph_only_compiler_rejects_non_definition_input() -> None:
    with pytest.raises(TypeError):
        HarnessGraphCompiler().compile(object())  # type: ignore[arg-type]


def _control_construct_definition() -> HarnessGraphDefinition:
    activity_ids = (
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
    )
    activities = tuple(
        HarnessStepSpec(
            step_id=activity_id,
            worker_type=HarnessWorkerType.FUNCTION,
            output_key=f"{activity_id}_output",
            quality_gate=f"{activity_id}.schema@1",
            side_effect_handler=(
                "publication.commit@2" if activity_id == "publish" else None
            ),
        )
        for activity_id in activity_ids
    )
    root = HarnessGraphSpec(
        graph_id="compiler.control-constructs",
        root=Sequence(
            (
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
                            condition=ConditionPredicate(
                                "quality_verdict.passed", "equals", True
                            ),
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
                    condition=ConditionPredicate(
                        "quality_verdict.passed", "equals", True
                    ),
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
                            condition=ConditionPredicate(
                                "graph.inputs.approved", "equals", True
                            ),
                        ),
                        ChoiceBranch(
                            "fallback",
                            StepRef("fallback"),
                            1,
                            is_default=True,
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
                activity_contract_ref="compiler.retract.activity@1",
            ),
        ),
        input_keys=("actor_id", "approved", "run_id", "tenant_id"),
        terminal_output_keys=("publish_output",),
    )
    return HarnessGraphDefinition(
        graph_id=root.graph_id,
        graph_version="7",
        root=root,
        activities=activities,
        leaf_activity_bindings=tuple(
            HarnessGraphLeafBinding(
                activity_id=activity.step_id,
                leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
                worker_ref=HarnessContractReference(
                    HarnessContractKind.WORKER,
                    f"compiler.{activity.step_id}.worker",
                    "1",
                ),
                activity_ref=HarnessContractReference(
                    HarnessContractKind.ACTIVITY,
                    f"compiler.{activity.step_id}.activity",
                    "1",
                ),
            )
            for activity in activities
        ),
        task_plan_stage_bindings=(),
        committed_output_bindings=(),
        repair_bindings=(),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="publication",
            version="4",
            handler="publication.commit@2",
            kind="publication",
            requires_approval=True,
            retry_limit=1,
        ),
    )
