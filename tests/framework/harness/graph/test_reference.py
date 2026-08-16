from __future__ import annotations

from business.research.graphs import (
    build_dynamic_paper_analysis_graph_definition,
)
from framework.harness.graph import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphCompiler,
    HarnessGraphReference,
)


def test_legacy_graph_reference_wire_contract_is_unchanged() -> None:
    reference = HarnessGraphReference(
        graph_id="legacy.graph",
        workflow_ref=HarnessContractReference(
            HarnessContractKind.WORKFLOW,
            "legacy.workflow",
            "1",
        ),
        schema_version=NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum="sha256:" + "1" * 64,
    )
    payload = {
        "graph_id": "legacy.graph",
        "workflow_ref": {
            "contract_kind": "workflow",
            "contract_id": "legacy.workflow",
            "version": "1",
        },
        "schema_version": NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "checksum": "sha256:" + "1" * 64,
    }

    assert reference.to_dict() == payload
    assert HarnessGraphReference.from_dict(payload) == reference


def test_graph_only_reference_round_trips_exact_compiler_identity() -> None:
    graph = HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph
    reference = HarnessGraphReference.from_graph(graph)
    payload = reference.to_dict()

    assert graph.graph_ref is not None
    assert reference.schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
    assert payload == {
        "graph_id": graph.graph_id,
        "graph_ref": graph.graph_ref.to_dict(),
        "schema_version": graph.schema_version,
        "compiler_version": graph.compiler_version,
        "condition_policy_version": graph.condition_policy_version,
        "checksum": graph.checksum,
    }
    assert "workflow_ref" not in payload
    assert HarnessGraphReference.from_dict(payload) == reference
