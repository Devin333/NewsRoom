from __future__ import annotations

import pytest

from backend.research.graphs import (
    build_dynamic_paper_analysis_graph_definition,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphCompiler,
    HarnessGraphReference,
)


_RETIRED_NORMALIZED_GRAPH_SCHEMA = "newsroom.harness-normalized-graph/v1"


def test_live_graph_reference_rejects_legacy_v1_wire_contract() -> None:
    payload = {
        "graph_id": "legacy.graph",
        "workflow_ref": {
            "contract_kind": "workflow",
            "contract_id": "legacy.workflow",
            "version": "1",
        },
        "schema_version": _RETIRED_NORMALIZED_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "checksum": "sha256:" + "1" * 64,
    }

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphReference.from_dict(payload)
    assert captured.value.code == "legacy_graph_schema_forbidden"


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
