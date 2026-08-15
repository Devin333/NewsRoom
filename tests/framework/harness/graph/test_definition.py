from __future__ import annotations

import json

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import (
    HARNESS_GRAPH_DEFINITION_SCHEMA,
    HarnessGraphDefinition,
    HarnessGraphDefinitionReader,
    HarnessGraphSpec,
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
    assert restored.activity_ids == ("load_source", "publish_artifacts")
    assert restored.root.graph_id == restored.graph_id
    assert restored.definition_checksum == definition.definition_checksum
    assert "workflow_id" not in payload
    assert "entry_step_id" not in payload
    assert "routing_rules" not in payload
    restored.verify_integrity()


def test_graph_definition_activity_order_does_not_change_checksum() -> None:
    first, second = _activities()

    forward = _definition(activities=(first, second))
    reverse = _definition(activities=(second, first))

    assert forward.activities == reverse.activities
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
                root=Sequence((StepRef("load_source"), StepRef("publish_artifacts"))),
            )
        )

    assert raised.value.code == "graph_definition_identity_mismatch"


def test_graph_definition_rejects_duplicate_activity_identity() -> None:
    first, _ = _activities()

    with pytest.raises(HarnessValidationError) as raised:
        _definition(activities=(first, first))

    assert raised.value.code == "graph_duplicate_identity"


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
    payload["schema_version"] = "newsroom.harness-graph-definition/v2"

    with pytest.raises(HarnessValidationError) as raised:
        HarnessGraphDefinitionReader().read(
            payload,
            source_schema=HARNESS_GRAPH_DEFINITION_SCHEMA,
        )

    assert raised.value.code == "unsupported_graph_definition_schema"


def _definition(
    *,
    graph_version: str = "1",
    root: HarnessGraphSpec | None = None,
    activities: tuple[HarnessStepSpec, ...] | None = None,
) -> HarnessGraphDefinition:
    return HarnessGraphDefinition(
        graph_id="research.paper-analysis",
        graph_version=graph_version,
        root=root
        or HarnessGraphSpec(
            graph_id="research.paper-analysis",
            root=Sequence(
                (StepRef("load_source"), StepRef("publish_artifacts"))
            ),
            terminal_output_keys=("artifact_refs",),
        ),
        activities=activities or _activities(),
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
            worker_type=HarnessWorkerType.SCRIPT,
            output_key="paper_source",
            quality_gate="PaperSourceLineageGate@1",
            metadata={"owner": "research"},
        ),
        HarnessStepSpec(
            step_id="publish_artifacts",
            worker_type=HarnessWorkerType.ARTIFACT,
            input_keys=("paper_source",),
            output_key="artifact_refs",
            side_effect_handler="research.artifact-bundle@1",
        ),
    )
