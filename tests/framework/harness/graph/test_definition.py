from __future__ import annotations

import json

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphDefinition,
    HarnessGraphDefinitionReader,
    HarnessGraphLeafBinding,
    HarnessGraphSpec,
    HarnessLeafActivityKind,
    HarnessStepSpec,
    HarnessTerminalSideEffectPolicy,
    HarnessWorkerType,
    Sequence,
    StepRef,
)


_SHA_A = "sha256:" + "a" * 64


def test_graph_definition_round_trips_with_canonical_checksum() -> None:
    definition = _definition()

    payload = json.loads(json.dumps(definition.to_dict()))
    restored = HarnessGraphDefinitionReader().read_for_execution(
        payload,
        source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
    )

    assert restored == definition
    assert restored.schema_version == HARNESS_GRAPH_DEFINITION_SCHEMA
    assert restored.activity_ids == ("compose_report", "load_source")
    assert tuple(
        binding.activity_id for binding in restored.leaf_activity_bindings
    ) == ("compose_report", "load_source")
    load_source_binding = restored.leaf_activity_binding("load_source")
    compose_report = restored.activity("compose_report")
    assert load_source_binding is not None
    assert load_source_binding.leaf_activity_kind is HarnessLeafActivityKind.FUNCTION
    assert restored.root.graph_id == restored.graph_id
    assert compose_report is not None
    assert compose_report.side_effect_handler is None
    assert restored.terminal_side_effect_policy.kind == "artifact_publication"
    assert restored.definition_checksum == definition.definition_checksum
    assert "workflow_id" not in payload
    assert "entry_step_id" not in payload
    assert "routing_rules" not in payload
    restored.verify_integrity()


def test_graph_definition_activity_order_does_not_change_checksum() -> None:
    first, second = _activities()
    first_binding, second_binding = _leaf_activity_bindings()

    forward = _definition(
        activities=(first, second),
        leaf_activity_bindings=(first_binding, second_binding),
    )
    reverse = _definition(
        activities=(second, first),
        leaf_activity_bindings=(second_binding, first_binding),
    )

    assert forward.activities == reverse.activities
    assert forward.leaf_activity_bindings == reverse.leaf_activity_bindings
    assert forward.definition_checksum == reverse.definition_checksum


def test_graph_definition_snapshots_mutable_activity_metadata() -> None:
    first, second = _activities()
    definition = _definition(activities=(first, second))

    first.metadata["owner"] = "changed-after-definition"

    assert definition.activity("load_source") is not None
    assert definition.activity("load_source").metadata == {"owner": "research"}
    with pytest.raises(TypeError):
        definition.activity("load_source").metadata["new"] = "value"


def test_graph_definition_rejects_nested_payload_tampering() -> None:
    payload = _definition().to_dict()
    payload["activities"][0]["worker_type"] = "llm"

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphDefinition.from_dict(payload)

    assert raised.value.code == "graph_definition_checksum_mismatch"


def test_graph_definition_rejects_leaf_binding_tampering() -> None:
    payload = _definition().to_dict()
    payload["leaf_activity_bindings"][0]["worker_ref"]["version"] = "2"

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphDefinition.from_dict(payload)

    assert raised.value.code == "graph_definition_checksum_mismatch"


def test_graph_definition_integrity_check_detects_in_memory_tampering() -> None:
    definition = _definition()
    object.__setattr__(definition, "graph_version", "2")

    with pytest.raises(HarnessValidationError) as raised:
        definition.verify_integrity()

    assert raised.value.code == "graph_definition_checksum_mismatch"


@pytest.mark.parametrize("graph_version", ["latest", "current", "default", "stable"])
def test_graph_definition_rejects_moving_versions(graph_version: str) -> None:
    with pytest.raises(HarnessValidationError) as raised:
        _definition(graph_version=graph_version)

    assert raised.value.code == "graph_inexact_version_reference"


def test_graph_definition_rejects_root_identity_mismatch() -> None:
    with pytest.raises(HarnessValidationError) as raised:
        _definition(
            root=HarnessGraphSpec(
                graph_id="research.other",
                root=Sequence((StepRef("load_source"), StepRef("compose_report"))),
            )
        )

    assert raised.value.code == "graph_definition_identity_mismatch"


def test_graph_definition_rejects_duplicate_activity_identity() -> None:
    first, _ = _activities()

    with pytest.raises(HarnessValidationError) as raised:
        _definition(activities=(first, first))

    assert raised.value.code == "graph_duplicate_identity"


def test_graph_definition_rejects_duplicate_leaf_binding_identity() -> None:
    first, _ = _leaf_activity_bindings()

    with pytest.raises(HarnessValidationError) as raised:
        _definition(leaf_activity_bindings=(first, first))

    assert raised.value.code == "graph_duplicate_identity"


def test_graph_definition_requires_every_typed_leaf_binding() -> None:
    first, _ = _leaf_activity_bindings()

    with pytest.raises(HarnessValidationError) as raised:
        _definition(leaf_activity_bindings=(first,))

    assert raised.value.code == "graph_leaf_activity_binding_coverage_mismatch"
    assert raised.value.details["missing"] == ["compose_report"]


def test_graph_definition_rejects_binding_for_internal_task_plan_stage() -> None:
    activity = HarnessStepSpec(
        step_id="dynamic_stage",
        worker_type=HarnessWorkerType.TASK_PLAN,
    )
    binding = _leaf_binding(
        "dynamic_stage",
        HarnessLeafActivityKind.FUNCTION,
    )

    with pytest.raises(HarnessValidationError) as raised:
        _definition(
            root=HarnessGraphSpec(
                graph_id="research.paper-analysis",
                root=StepRef("dynamic_stage"),
            ),
            activities=(activity,),
            leaf_activity_bindings=(binding,),
        )

    assert raised.value.code == "graph_leaf_activity_binding_coverage_mismatch"
    assert raised.value.details["unexpected"] == ["dynamic_stage"]


def test_graph_definition_allows_internal_task_plan_without_leaf_alias() -> None:
    activity = HarnessStepSpec(
        step_id="dynamic_stage",
        worker_type=HarnessWorkerType.TASK_PLAN,
    )

    definition = _definition(
        root=HarnessGraphSpec(
            graph_id="research.paper-analysis",
            root=StepRef("dynamic_stage"),
        ),
        activities=(activity,),
        leaf_activity_bindings=(),
    )

    assert definition.leaf_activity_bindings == ()


def test_graph_definition_rejects_leaf_kind_worker_type_mismatch() -> None:
    _, second = _leaf_activity_bindings()
    mismatched = _leaf_binding(
        "load_source",
        HarnessLeafActivityKind.TOOL,
    )

    with pytest.raises(HarnessValidationError) as raised:
        _definition(leaf_activity_bindings=(mismatched, second))

    assert raised.value.code == "graph_leaf_activity_kind_mismatch"
    assert raised.value.details["activity_id"] == "load_source"
    assert raised.value.details["actual_worker_type"] == "function"


def test_graph_definition_rejects_leaf_contract_kind_mismatch() -> None:
    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphLeafBinding(
            activity_id="load_source",
            leaf_activity_kind=HarnessLeafActivityKind.FUNCTION,
            worker_ref=HarnessContractReference(
                HarnessContractKind.ACTIVITY,
                "research.load_source",
                "1",
            ),
            activity_ref=HarnessContractReference(
                HarnessContractKind.ACTIVITY,
                "research.load_source",
                "v1",
            ),
        )

    assert raised.value.code == "graph_leaf_activity_contract_kind_mismatch"
    assert raised.value.details["field"] == "leaf_binding.worker_ref"


@pytest.mark.parametrize(
    "worker_type",
    (
        HarnessWorkerType.SCRIPT,
        HarnessWorkerType.MCP,
        HarnessWorkerType.ARTIFACT,
        HarnessWorkerType.QUALITY_GATE,
    ),
)
def test_graph_definition_rejects_legacy_or_owner_worker_types(
    worker_type: HarnessWorkerType,
) -> None:
    activity = HarnessStepSpec(
        step_id="legacy",
        worker_type=worker_type,
    )

    with pytest.raises(HarnessValidationError) as raised:
        _definition(
            root=HarnessGraphSpec(
                graph_id="research.paper-analysis",
                root=StepRef("legacy"),
            ),
            activities=(activity,),
            leaf_activity_bindings=(),
        )

    assert raised.value.code == "graph_unsupported_leaf_worker_type"
    assert raised.value.details["activities"] == {"legacy": worker_type.value}


def test_graph_reader_rejects_legacy_schema_and_fields() -> None:
    reader = HarnessGraphDefinitionReader()
    payload = _definition().to_dict()

    with pytest.raises(HarnessValidationError) as schema_error:
        reader.read(
            payload,
            source_schema="newsroom.harness-workflow-legacy/v1",
        )
    payload["workflow_id"] = "legacy"
    with pytest.raises(HarnessValidationError) as field_error:
        reader.read(
            payload,
            source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
        )

    assert schema_error.value.code == "unsupported_graph_definition_schema"
    assert field_error.value.code == "invalid_graph_definition"


def test_graph_reader_rejects_payload_schema_mismatch() -> None:
    payload = _definition().to_dict()
    payload["schema_version"] = "newsroom.harness-graph-definition/v1"

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphDefinitionReader().read(
            payload,
            source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
        )

    assert raised.value.code == "unsupported_graph_definition_schema"


def test_graph_reader_rejects_v1_payload_without_typed_leaf_bindings() -> None:
    payload = _definition().to_dict()
    payload.pop("leaf_activity_bindings")
    payload["schema_version"] = "newsroom.harness-graph-definition/v1"

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphDefinitionReader().read(
            payload,
            source_schema="newsroom.harness-graph-definition/v1",
        )

    assert raised.value.code == "unsupported_graph_definition_schema"


def _definition(
    *,
    graph_version: str = "1",
    root: HarnessGraphSpec | None = None,
    activities: tuple[HarnessStepSpec, ...] | None = None,
    leaf_activity_bindings: tuple[HarnessGraphLeafBinding, ...] | None = None,
) -> HarnessGraphDefinition:
    selected_activities = _activities() if activities is None else activities
    return HarnessGraphDefinition(
        graph_id="research.paper-analysis",
        graph_version=graph_version,
        root=root
        or HarnessGraphSpec(
            graph_id="research.paper-analysis",
            root=Sequence(
                (StepRef("load_source"), StepRef("compose_report"))
            ),
            terminal_output_keys=("report_draft",),
        ),
        activities=selected_activities,
        leaf_activity_bindings=(
            _leaf_activity_bindings()
            if leaf_activity_bindings is None and activities is None
            else (
                tuple(
                    _leaf_binding(
                        activity.step_id,
                        HarnessLeafActivityKind(activity.worker_type.value),
                    )
                    for activity in selected_activities
                    if activity.worker_type is not HarnessWorkerType.TASK_PLAN
                )
                if leaf_activity_bindings is None
                else leaf_activity_bindings
            )
        ),
        terminal_side_effect_policy=HarnessTerminalSideEffectPolicy(
            policy_id="research.artifact.publication",
            version="1",
            handler="research.artifact-bundle@1",
            kind="artifact_publication",
            requires_approval=False,
            retry_limit=2,
            not_required_evidence_ref=_SHA_A,
            inherited_gate_refs=("ResearchQualityGate@1",),
        ),
    )


def _activities() -> tuple[HarnessStepSpec, HarnessStepSpec]:
    return (
        HarnessStepSpec(
            step_id="load_source",
            worker_type=HarnessWorkerType.FUNCTION,
            output_key="paper_source",
            quality_gate="PaperSourceLineageGate@1",
            metadata={"owner": "research"},
        ),
        HarnessStepSpec(
            step_id="compose_report",
            worker_type=HarnessWorkerType.AGENT_LOOP,
            input_keys=("paper_source",),
            output_key="report_draft",
        ),
    )


def _leaf_activity_bindings() -> tuple[
    HarnessGraphLeafBinding,
    HarnessGraphLeafBinding,
]:
    return (
        _leaf_binding("load_source", HarnessLeafActivityKind.FUNCTION),
        _leaf_binding("compose_report", HarnessLeafActivityKind.AGENT_LOOP),
    )


def _leaf_binding(
    activity_id: str,
    kind: HarnessLeafActivityKind,
) -> HarnessGraphLeafBinding:
    return HarnessGraphLeafBinding(
        activity_id=activity_id,
        leaf_activity_kind=kind,
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            f"research.{activity_id}",
            "1",
        ),
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            f"research.{activity_id}",
            "v1",
        ),
    )
