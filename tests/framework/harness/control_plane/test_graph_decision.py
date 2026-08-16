from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_decision import (
    HarnessGraphDecision,
    HarnessGraphDecisionType,
)
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


def test_graph_step_decision_round_trips_with_stable_checksum() -> None:
    decision = _step_decision()
    repeated = _step_decision()
    restored = HarnessGraphDecision.from_dict(decision.to_dict())

    assert decision == repeated
    assert decision.decision_checksum == repeated.decision_checksum
    assert restored == decision
    assert restored.to_dict() == decision.to_dict()
    assert "decided_at" not in decision.to_dict()
    assert decision.target_node_ids == ("repair-first", "repair-second")


def test_graph_decision_checksum_rejects_projection_tampering() -> None:
    payload = _step_decision().to_dict()
    payload["reason_code"] = "tampered"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphDecision.from_dict(payload)

    assert captured.value.code == "graph_decision_checksum_mismatch"


def test_binding_mapping_permutation_cannot_change_decision_identity() -> None:
    first = _step_decision(
        binding_versions={
            "step": "research:analyze@1",
            "worker": "worker@1",
            "activity": "worker.activity@1",
        }
    )
    second = _step_decision(
        binding_versions={
            "activity": "worker.activity@1",
            "worker": "worker@1",
            "step": "research:analyze@1",
        }
    )

    assert first.binding_versions == second.binding_versions
    assert first.decision_checksum == second.decision_checksum
    assert first.to_dict() == second.to_dict()


def test_graph_activation_requires_definition_without_preallocated_instance() -> None:
    valid = HarnessGraphDecision(
        "activate_node",
        "run-1",
        _graph_ref(),
        _sha("state"),
        _sha("observations"),
        "entry_ready",
        node_id="entry",
    )

    assert valid.decision_type is HarnessGraphDecisionType.ACTIVATE_NODE
    with pytest.raises(HarnessValidationError) as missing_definition:
        HarnessGraphDecision(
            "activate_node",
            "run-1",
            _graph_ref(),
            _sha("state"),
            _sha("observations"),
            "entry_ready",
        )
    with pytest.raises(HarnessValidationError) as preallocated_instance:
        HarnessGraphDecision(
            "activate_node",
            "run-1",
            _graph_ref(),
            _sha("state"),
            _sha("observations"),
            "entry_ready",
            node_id="entry",
            node_instance_id="instance",
        )

    assert missing_definition.value.code == "graph_decision_identity_mismatch"
    assert preallocated_instance.value.code == "graph_decision_identity_mismatch"


def test_step_and_control_decisions_enforce_separate_identity_contracts() -> None:
    with pytest.raises(HarnessValidationError) as missing_step_identity:
        HarnessGraphDecision(
            "enter_step_phase",
            "run-1",
            _graph_ref(),
            _sha("state"),
            _sha("observations"),
            "plan_required",
            node_id="step",
            node_instance_id="instance",
        )
    with pytest.raises(HarnessValidationError) as control_step_leak:
        HarnessGraphDecision(
            "select_choice",
            "run-1",
            _graph_ref(),
            _sha("state"),
            _sha("observations"),
            "branch_selected",
            node_id="choice",
            node_instance_id="instance",
            step_ref=_step_ref(),
            attempt=0,
        )

    assert missing_step_identity.value.code == "graph_decision_step_identity_missing"
    assert control_step_leak.value.code == "graph_decision_identity_mismatch"


def test_graph_decision_rejects_callable_payload_and_moving_version_alias() -> None:
    with pytest.raises(HarnessValidationError) as callable_payload:
        _step_decision(payload={"callback": lambda: None})
    with pytest.raises(HarnessValidationError) as moving_version:
        _step_decision(binding_versions={"worker": "latest"})

    assert callable_payload.value.code == "graph_non_canonical_value"
    assert moving_version.value.code == "graph_decision_inexact_version"


def test_step_decision_requires_complete_exact_runtime_bindings() -> None:
    with pytest.raises(HarnessValidationError) as missing:
        _step_decision(binding_versions={})
    with pytest.raises(HarnessValidationError) as range_version:
        _step_decision(
            binding_versions={
                "step": "research:analyze@1",
                "worker": "worker@^1",
                "activity": "worker.activity@1",
            }
        )
    with pytest.raises(HarnessValidationError) as noncanonical_version:
        _step_decision(
            binding_versions={
                "step": "research:analyze@1",
                "worker": "worker@1 ",
                "activity": "worker.activity@1",
            }
        )

    assert missing.value.code == "graph_decision_binding_missing"
    assert range_version.value.code == "graph_decision_inexact_version"
    assert noncanonical_version.value.code == "graph_decision_inexact_version"


def test_activity_dispatch_requires_positive_target_attempt() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        _step_decision(decision_type="dispatch_activity", attempt=0)

    valid = _step_decision(decision_type="dispatch_activity", attempt=1)

    assert captured.value.code == "invalid_graph_decision_attempt"
    assert valid.attempt == 1


def test_compensation_schedule_requires_definition_and_exact_bindings() -> None:
    base = {
        "decision_type": "schedule_compensation",
        "run_id": "run-1",
        "graph_ref": _graph_ref(),
        "input_projection_checksum": _sha("state"),
        "observation_checksum": _sha("observations"),
        "reason_code": "compensation_required",
    }
    with pytest.raises(HarnessValidationError) as missing_identity:
        HarnessGraphDecision(**base)
    with pytest.raises(HarnessValidationError) as missing_bindings:
        HarnessGraphDecision(**base, node_id="undo")

    valid = HarnessGraphDecision(
        **base,
        node_id="undo",
        binding_versions={
            "compensation": "publication.undo@1",
            "activity": "publication.undo.activity@1",
        },
    )

    assert missing_identity.value.code == "graph_decision_identity_mismatch"
    assert missing_bindings.value.code == "graph_decision_binding_missing"
    assert valid.node_id == "undo"


def _step_decision(
    *,
    binding_versions=None,
    payload=None,
    decision_type: str = "enter_step_phase",
    attempt: int = 0,
) -> HarnessGraphDecision:
    return HarnessGraphDecision(
        decision_type=decision_type,
        run_id="run-1",
        graph_ref=_graph_ref(),
        input_projection_checksum=_sha("state"),
        observation_checksum=_sha("observations"),
        reason_code="plan_required",
        node_id="analyze",
        node_instance_id="hni-analyze",
        step_ref=_step_ref(),
        attempt=attempt,
        target_node_ids=("repair-first", "repair-second"),
        evidence_refs=(_sha("gate"), _sha("activity")),
        binding_versions=(
            {
                "step": "research:analyze@1",
                "worker": "worker@1",
                "activity": "worker.activity@1",
                "gate:quality": "quality@2",
            }
            if binding_versions is None
            else binding_versions
        ),
        payload={"phase": "plan"} if payload is None else payload,
    )


def _graph_ref() -> HarnessGraphReference:
    return HarnessGraphReference(
        "graph",
        HarnessContractReference(HarnessContractKind.WORKFLOW, "research", "2"),
        NORMALIZED_HARNESS_GRAPH_SCHEMA,
        HARNESS_GRAPH_COMPILER_VERSION,
        HARNESS_CONDITION_POLICY_VERSION,
        _sha("graph"),
    )


def _step_ref() -> HarnessContractReference:
    return HarnessContractReference(
        HarnessContractKind.STEP,
        "research:analyze",
        "1",
    )


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})
