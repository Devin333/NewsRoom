from __future__ import annotations

import json

from business.research.graphs import (
    RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_ID,
    RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION,
    RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_PAPER_ANALYSIS_GRAPH_ID,
    RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION,
    build_dynamic_paper_analysis_graph_definition,
    build_paper_analysis_graph_definition,
)
from business.research.graphs.contracts import (
    RESEARCH_DYNAMIC_OUTPUT_ROLES,
    RESEARCH_DYNAMIC_POLICY_REF,
    RESEARCH_DYNAMIC_STAGE_ID,
    RESEARCH_DYNAMIC_TASK_PLAN_SUPPORT_REFS,
)
from business.research.ports.artifact_publication import (
    RESEARCH_ARTIFACT_EFFECT_KIND,
    RESEARCH_ARTIFACT_HANDLER_REF,
)
from business.research.workflows.paper_analysis_gates import (
    build_paper_analysis_gate_registry,
)
from framework.harness.graph import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
    HarnessContractKind,
    HarnessGraphDefinition,
    HarnessGraphDefinitionReader,
    HarnessLeafActivityKind,
    HarnessWorkerType,
)


_EXPECTED_GATES = {
    "load_paper_source": "PaperSourceLineageGate@1",
    "compile_document": "ResearchDocumentSchemaGate@1",
    "run_research_rag": "ResearchRAGContextProjectionGate@1",
    "build_evidence_pack": "ResearchEvidenceCoverageGate@1",
    "analyze_structure": "SummarySchemaGate@1",
    "analyze_contribution": "SummaryEvidenceCoverageGate@1",
    "analyze_experiments": "BenchmarkEvidenceLineageGate@1",
    "verify_claims": "ClaimEvidenceGate@1",
    "quality_gate": "ResearchQualityGate@1",
    "build_reader_payload": "ReaderPayloadSchemaGate@1",
    "build_paper_card": "ResearchPaperCardGate@1",
    "publish_artifacts": None,
}


def test_static_paper_analysis_declares_graph_only_parallel_topology() -> None:
    definition = build_paper_analysis_graph_definition()

    assert isinstance(definition, HarnessGraphDefinition)
    assert definition.graph_id == RESEARCH_PAPER_ANALYSIS_GRAPH_ID
    assert definition.graph_version == RESEARCH_PAPER_ANALYSIS_GRAPH_VERSION
    assert definition.root.input_keys == (
        "paper_id",
        "source_ref",
        "memory_namespace",
    )
    assert definition.root.terminal_output_keys == (
        "research_quality",
        "reader_payload",
        "paper_card",
        "artifact_candidate_bundle",
    )
    payload = definition.to_dict()
    assert not _recursive_keys(payload).intersection(
        {"workflow_id", "workflow_version", "workflow_ref", "routing_rules"}
    )

    root = definition.root.to_dict()["root"]
    parallel = root["children"][4]
    assert root["kind"] == "sequence"
    assert parallel["kind"] == "parallel_all"
    assert parallel["fork_id"] == "analysis_fork"
    assert parallel["join_id"] == "analysis_join"
    assert [branch["branch_id"] for branch in parallel["branches"]] == [
        "structure",
        "contribution",
        "experiments",
    ]
    assert parallel["merge"] == {
        "kind": "aggregation_step",
        "step": {
            "kind": "step",
            "step_id": "verify_claims",
            "node_id": "verify_claims",
        },
        "branch_inputs_key": "analysis_branch_refs",
    }


def test_static_paper_analysis_pins_typed_leaf_and_gate_contracts() -> None:
    definition = build_paper_analysis_graph_definition()
    activities = {
        activity.step_id: activity for activity in definition.activities
    }
    bindings = {
        binding.activity_id: binding
        for binding in definition.leaf_activity_bindings
    }

    assert {name: activity.quality_gate for name, activity in activities.items()} == (
        _EXPECTED_GATES
    )
    assert set(bindings) == set(activities)
    for activity_id, activity in activities.items():
        binding = bindings[activity_id]
        assert binding.expected_worker_type is activity.worker_type
        assert binding.worker_ref.contract_kind is HarnessContractKind.WORKER
        assert binding.activity_ref.contract_kind is HarnessContractKind.ACTIVITY
        assert binding.worker_ref.exact_ref == (
            f"research.paper_analysis.{activity_id}@1"
        )
        assert binding.activity_ref.exact_ref == (
            f"research.paper_analysis.{activity_id}@1"
        )

    assert {
        activities[name].worker_type
        for name in (
            "analyze_structure",
            "analyze_contribution",
            "analyze_experiments",
        )
    } == {HarnessWorkerType.SUBAGENT}
    assert all(
        activity.worker_type is HarnessWorkerType.FUNCTION
        for name, activity in activities.items()
        if not name.startswith("analyze_")
    )

    gate_registry = build_paper_analysis_gate_registry()
    for gate_ref in sorted(set(_EXPECTED_GATES.values()) - {None}):
        assert str(gate_registry.resolve(gate_ref).reference) == gate_ref


def test_artifact_activity_prepares_candidate_and_terminal_policy_publishes() -> (
    None
):
    definition = build_paper_analysis_graph_definition()
    activity = definition.activity("publish_artifacts")
    binding = definition.leaf_activity_binding("publish_artifacts")

    assert activity is not None
    assert binding is not None
    assert activity.worker_type is HarnessWorkerType.FUNCTION
    assert binding.leaf_activity_kind is HarnessLeafActivityKind.FUNCTION
    assert activity.output_key == "artifact_candidate_bundle"
    assert "artifact_refs" not in definition.root.terminal_output_keys
    assert str(activity.side_effect_handler) == RESEARCH_ARTIFACT_HANDLER_REF
    assert activity.metadata["candidate_only"] is True
    assert "approval_required" not in activity.metadata

    terminal = definition.terminal_side_effect_policy
    assert terminal.policy_id == RESEARCH_ARTIFACT_TERMINAL_POLICY_ID
    assert terminal.version == RESEARCH_ARTIFACT_TERMINAL_POLICY_VERSION
    assert str(terminal.handler) == RESEARCH_ARTIFACT_HANDLER_REF
    assert terminal.kind == RESEARCH_ARTIFACT_EFFECT_KIND
    assert terminal.requires_approval is False
    assert terminal.retry_limit == 2
    assert (
        terminal.not_required_evidence_ref
        == RESEARCH_ARTIFACT_NOT_REQUIRED_EVIDENCE_REF
    )
    assert terminal.inherited_gate_refs == ("ResearchQualityGate@1",)


def test_dynamic_graph_replaces_only_static_analysis_fanout() -> None:
    static = build_paper_analysis_graph_definition()
    dynamic = build_dynamic_paper_analysis_graph_definition()

    assert dynamic.graph_id == RESEARCH_DYNAMIC_PAPER_ANALYSIS_GRAPH_ID
    assert dynamic.definition_checksum != static.definition_checksum
    assert RESEARCH_DYNAMIC_STAGE_ID in dynamic.activity_ids
    assert not {
        "analyze_structure",
        "analyze_contribution",
        "analyze_experiments",
    }.intersection(dynamic.activity_ids)
    assert dynamic.task_plan_stage_binding(RESEARCH_DYNAMIC_STAGE_ID) is not None
    assert dynamic.leaf_activity_binding(RESEARCH_DYNAMIC_STAGE_ID) is None

    stage = dynamic.activity(RESEARCH_DYNAMIC_STAGE_ID)
    binding = dynamic.task_plan_stage_binding(RESEARCH_DYNAMIC_STAGE_ID)
    assert stage is not None
    assert binding is not None
    assert stage.worker_type is HarnessWorkerType.TASK_PLAN
    assert stage.input_keys == ("document", "evidence_pack")
    assert stage.output_key == "analysis_branch_refs"
    assert binding.worker_ref.exact_ref == (
        "research.paper_analysis.dynamic_analysis_stage@1"
    )
    assert binding.activity_ref.exact_ref == (
        "research.paper_analysis.dynamic_analysis_stage@1"
    )
    assert binding.policy_ref == RESEARCH_DYNAMIC_POLICY_REF
    assert binding.task_plan_schema == "newsroom.harness-task-plan/v1"
    assert binding.required_output_roles == tuple(
        sorted(RESEARCH_DYNAMIC_OUTPUT_ROLES)
    )
    assert dict(binding.support_refs) == dict(
        RESEARCH_DYNAMIC_TASK_PLAN_SUPPORT_REFS
    )

    dynamic_children = dynamic.root.to_dict()["root"]["children"]
    assert [child["step_id"] for child in dynamic_children] == [
        "load_paper_source",
        "compile_document",
        "run_research_rag",
        "build_evidence_pack",
        RESEARCH_DYNAMIC_STAGE_ID,
        "verify_claims",
        "quality_gate",
        "build_reader_payload",
        "build_paper_card",
        "publish_artifacts",
    ]


def test_research_graph_definitions_are_canonical_and_strictly_readable() -> (
    None
):
    for builder in (
        build_paper_analysis_graph_definition,
        build_dynamic_paper_analysis_graph_definition,
    ):
        first = builder()
        second = builder()
        payload = json.loads(json.dumps(first.to_dict()))
        restored = HarnessGraphDefinitionReader().read_for_execution(
            payload,
            source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
        )

        assert first.definition_checksum == second.definition_checksum
        assert restored == first
        restored.verify_integrity()


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(_recursive_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value))
    return set()
