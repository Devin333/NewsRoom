from __future__ import annotations

import pytest

from business.research.graphs import build_dynamic_paper_analysis_graph_definition
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


def test_live_compiler_and_writer_emit_graph_v2_without_workflow_identity() -> None:
    graph = HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph

    payload = graph.to_dict()
    assert graph.schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
    assert graph.compiler_version == HARNESS_GRAPH_ONLY_COMPILER_VERSION
    assert not {"workflow_id", "workflow_version", "workflow_ref"}.intersection(
        payload
    )
    assert HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph.from_dict(payload) == graph


def test_live_normalized_graph_reader_rejects_legacy_v1_payload() -> None:
    graph = HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph
    payload = graph.to_dict()
    payload.update(
        {
            "schema_version": _RETIRED_NORMALIZED_GRAPH_SCHEMA,
            "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
            "workflow_id": graph.graph_id,
            "workflow_version": "1",
            "workflow_ref": {
                "contract_kind": "workflow",
                "contract_id": graph.graph_id,
                "version": "1",
            },
        }
    )
    with pytest.raises(HarnessValidationError) as captured:
        type(graph).from_dict(payload)
    assert captured.value.code == "legacy_graph_schema_forbidden"


def test_live_graph_reference_rejects_legacy_v1_identity() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphReference(
            graph_id="legacy.graph",
            graph_ref=HarnessContractReference(
                HarnessContractKind.GRAPH,
                "legacy.workflow",
                "1",
            ),
            schema_version=_RETIRED_NORMALIZED_GRAPH_SCHEMA,
            compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
            condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
            checksum="sha256:" + "1" * 64,
        )
    assert captured.value.code == "legacy_graph_schema_forbidden"
