from __future__ import annotations

import json

from business.research.graphs import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
    READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    READER_REPAIR_EXECUTION_GATE_REFERENCES,
    READER_REPAIR_GATE_REFERENCES,
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    READER_REPAIR_MEMORY_EFFECT_KIND,
    READER_REPAIR_MEMORY_HANDLER_REF,
    READER_REPAIR_MEMORY_POLICY_ID,
    READER_REPAIR_MEMORY_POLICY_VERSION,
    READER_REPAIR_SUBAGENT_IDS,
    READER_REPAIR_SUBAGENT_WORKER_REFS,
    READER_REPAIR_RESULT_STEP_ID,
    build_reader_repair_execution_gate_registry,
    build_reader_repair_gate_registry,
    build_reader_repair_graph_definition,
    build_reader_repair_subagent_specs,
)
from framework.harness.graph import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
    HarnessGraphDefinitionReader,
    HarnessLeafActivityKind,
    HarnessGraphRepairTrigger,
    HarnessWorkerType,
)


_ACTIVITY_GATES = {
    "detect_reader_issue": "ReaderRepairIssueGate@1",
    "assemble_repair_context": "ReaderRepairContextGate@1",
    "propose_repair_candidate": "ReaderRepairPatchCandidateGate@1",
    "apply_repair_candidate": "ReaderRepairApplicationCandidateGate@1",
    "collect_repair_application_observation": (
        "ReaderRepairApplicationObservationGate@1"
    ),
    "verify_repair_application": "ReaderRepairApplicationVerificationGate@1",
    "build_repair_result": "ReaderRepairCommittedResultGate@1",
    "build_repair_case": "ReaderRepairCaseGate@1",
    "prepare_skill_candidate_bundle": "ReaderRepairStrategyBoundaryGate@1",
    "prepare_memory_write": "ReaderRepairMemoryPolicyGate@1",
}


def test_reader_repair_graph_declares_exact_candidate_pipeline() -> None:
    definition = build_reader_repair_graph_definition()

    assert definition.graph_id == READER_REPAIR_GRAPH_ID
    assert definition.graph_version == READER_REPAIR_GRAPH_VERSION
    assert definition.root.input_keys == (
        "reader_payload",
        "run_id",
        "source_format",
    )
    assert definition.root.terminal_output_keys == (
        "reader_repair_result",
        "reader_repair_case",
        "strategy_candidate_bundle",
        "memory_write_candidate",
    )
    children = definition.root.to_dict()["root"]["children"]
    assert [child["step_id"] for child in children] == list(_ACTIVITY_GATES)
    assert {
        activity.step_id: activity.quality_gate
        for activity in definition.activities
    } == _ACTIVITY_GATES
    declared_gates = set(_ACTIVITY_GATES.values())
    assert declared_gates.issubset(
        set(READER_REPAIR_GATE_REFERENCES)
        | set(READER_REPAIR_EXECUTION_GATE_REFERENCES)
    )
    assert "ReaderRepairCandidateGate@1" not in declared_gates
    assert "ReaderRepairVerificationObservationGate@1" not in declared_gates
    assert "ReaderRepairResultGate@1" not in declared_gates


def test_reader_repair_graph_pins_typed_leaf_and_subagent_contracts() -> None:
    definition = build_reader_repair_graph_definition()
    activities = {
        activity.step_id: activity for activity in definition.activities
    }
    bindings = {
        binding.activity_id: binding
        for binding in definition.leaf_activity_bindings
    }

    assert set(bindings) == set(activities)
    assert activities["propose_repair_candidate"].worker_type is (
        HarnessWorkerType.SUBAGENT
    )
    assert activities["collect_repair_application_observation"].worker_type is (
        HarnessWorkerType.SUBAGENT
    )
    assert all(
        activity.worker_type is HarnessWorkerType.FUNCTION
        for activity_id, activity in activities.items()
        if activity_id not in READER_REPAIR_SUBAGENT_IDS
    )
    for activity_id, binding in bindings.items():
        assert binding.leaf_activity_kind is HarnessLeafActivityKind(
            activities[activity_id].worker_type.value
        )
        assert binding.activity_ref.exact_ref == (
            f"research.reader_repair.{activity_id}@1"
        )
    for activity_id, worker_ref in READER_REPAIR_SUBAGENT_WORKER_REFS.items():
        assert bindings[activity_id].worker_ref.exact_ref == worker_ref

    proposer, verifier = build_reader_repair_subagent_specs()
    assert proposer.subagent_id == READER_REPAIR_SUBAGENT_IDS[
        "propose_repair_candidate"
    ]
    assert verifier.subagent_id == READER_REPAIR_SUBAGENT_IDS[
        "collect_repair_application_observation"
    ]
    assert proposer.metadata["candidate_only"] is True
    assert verifier.metadata["candidate_only"] is True
    assert "metadata" in proposer.output_schema["required"]
    assert "metadata" in verifier.output_schema["required"]
    assert verifier.context_policy["allow_proposer_private_notes"] is False
    assert "passed" not in verifier.output_schema["required"]
    assert "verdict" not in verifier.output_schema["required"]
    assert proposer.budget["max_memory_ops"] == 0
    assert verifier.budget["max_memory_ops"] == 0


def test_reader_repair_graph_binds_committed_application_and_bounded_repair() -> None:
    definition = build_reader_repair_graph_definition()

    assert len(definition.committed_output_bindings) == 1
    binding = definition.committed_output_bindings[0]
    assert binding.binding_id == READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID
    assert binding.producer_activity_id == READER_REPAIR_APPLICATION_STEP_ID
    assert binding.producer_node_id == READER_REPAIR_APPLICATION_STEP_ID
    assert binding.producer_output_key == READER_REPAIR_APPLICATION_OUTPUT_KEY
    assert binding.consumer_activity_id == READER_REPAIR_RESULT_STEP_ID
    assert binding.consumer_node_id == READER_REPAIR_RESULT_STEP_ID
    assert binding.receipt_input_key == READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY

    expected_repair_sources = {
        "propose_repair_candidate",
        READER_REPAIR_APPLICATION_STEP_ID,
        "collect_repair_application_observation",
        READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
    }
    assert {item.source_node_id for item in definition.repair_bindings} == (
        expected_repair_sources
    )
    assert len({item.repair_node_id for item in definition.repair_bindings}) == 4
    assert all(
        item.repair_activity_id == "propose_repair_candidate"
        and set(item.triggers)
        == {
            HarnessGraphRepairTrigger.WORKER_FAILURE_AFTER_RETRY_EXHAUSTION,
            HarnessGraphRepairTrigger.VERIFICATION_FAILURE,
        }
        for item in definition.repair_bindings
    )
    assert all(
        activity.retry_policy.repair_step_id is None
        for activity in definition.activities
    )
    assert definition.activity("propose_repair_candidate").retry_policy.to_dict() == {
        "max_retries": 1,
        "max_attempts": 2,
        "effective_max_attempts": 2,
        "retry_on_statuses": ["failed"],
        "backoff_seconds": 0.0,
        "repair_step_id": None,
        "fail_fast_error_types": [],
    }
    assert definition.activity(
        "collect_repair_application_observation"
    ).retry_policy.effective_max_attempts == 2
    assert definition.activity(
        READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID
    ).output_key == READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY


def test_reader_repair_memory_and_skill_authority_stays_with_harness() -> None:
    definition = build_reader_repair_graph_definition()
    memory_activity = definition.activity("prepare_memory_write")
    memory_binding = definition.leaf_activity_binding("prepare_memory_write")
    strategy_activity = definition.activity("prepare_skill_candidate_bundle")

    assert memory_activity is not None
    assert memory_binding is not None
    assert strategy_activity is not None
    assert memory_activity.worker_type is HarnessWorkerType.FUNCTION
    assert memory_binding.leaf_activity_kind is HarnessLeafActivityKind.FUNCTION
    assert memory_activity.output_key == "memory_write_candidate"
    assert memory_activity.metadata["candidate_only"] is True
    assert str(memory_activity.side_effect_handler) == (
        READER_REPAIR_MEMORY_HANDLER_REF
    )
    assert strategy_activity.metadata["candidate_only"] is True
    assert strategy_activity.metadata["requires_harness_skill_evolution"] is True
    assert strategy_activity.side_effect_handler is None

    terminal = definition.terminal_side_effect_policy
    assert terminal.policy_id == READER_REPAIR_MEMORY_POLICY_ID
    assert terminal.version == READER_REPAIR_MEMORY_POLICY_VERSION
    assert str(terminal.handler) == READER_REPAIR_MEMORY_HANDLER_REF
    assert terminal.kind == READER_REPAIR_MEMORY_EFFECT_KIND
    assert terminal.inherited_gate_refs == ("ReaderRepairMemoryPolicyGate@1",)
    assert terminal.requires_approval is False

    serialized = json.dumps(definition.to_dict(), sort_keys=True)
    assert "artifact" not in serialized.casefold()
    assert "active_skill_package" not in serialized
    assert "production_skill_version" not in serialized
    assert "memory_ref" not in definition.root.terminal_output_keys


def test_reader_repair_graph_is_canonical_strict_and_gate_complete() -> None:
    first = build_reader_repair_graph_definition()
    second = build_reader_repair_graph_definition()
    restored = HarnessGraphDefinitionReader().read_for_execution(
        json.loads(json.dumps(first.to_dict())),
        source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
    )
    legacy_registry = build_reader_repair_gate_registry()
    execution_registry = build_reader_repair_execution_gate_registry(
        graph_definition_checksum=first.definition_checksum,
    )

    assert first.definition_checksum == second.definition_checksum
    assert restored == first
    restored.verify_integrity()
    for reference in _ACTIVITY_GATES.values():
        registry = (
            execution_registry
            if reference in READER_REPAIR_EXECUTION_GATE_REFERENCES
            else legacy_registry
        )
        assert str(registry.resolve(reference).reference) == reference
