from __future__ import annotations

import pytest

from framework.events.canonical import BusinessContext
from framework.events.errors import EventCanonicalizationError, EventSchemaError, EventUnknownSchemaError
from framework.events.schema.catalog import EventSchemaCatalog, EventSchemaRegistration, default_event_schema_catalog


def test_default_catalog_has_no_workflow_event_or_operation_reader() -> None:
    catalog = default_event_schema_catalog()

    for event_type, data_schema in (
        ("workflow_started", "newsroom.workflow-event/v1"),
        ("run_operation_requested", "newsroom.workflow-operation/v1"),
    ):
        with pytest.raises(EventUnknownSchemaError):
            catalog.get(event_type, data_schema)
        with pytest.raises(EventUnknownSchemaError):
            catalog.current_schema(event_type)

    assert all(
        "workflow" not in registration.data_schema
        for registration in catalog.registrations()
    )


def test_business_context_accepts_only_graph_orchestration_identity() -> None:
    context = BusinessContext.from_dict(
        {
            "run_id": "run-1",
            "graph_id": "research.paper-analysis",
            "graph_version": "1",
            "graph_ref": "research.paper-analysis@1",
            "graph_checksum": "sha256:" + "a" * 64,
            "stage_id": "run_research_rag",
        }
    )

    assert context.graph_ref == "research.paper-analysis@1"
    assert context.stage_id == "run_research_rag"
    with pytest.raises(EventCanonicalizationError, match="workflow_id"):
        BusinessContext.from_dict({"workflow_id": "legacy"})
    with pytest.raises(EventCanonicalizationError, match="step_id"):
        BusinessContext.from_dict({"step_id": "legacy"})


def test_catalog_keeps_one_current_schema_per_graph_event_type() -> None:
    catalog = EventSchemaCatalog()
    registration = EventSchemaRegistration(
        event_type="graph_node_verified",
        data_schema="newsroom.graph-node-verified/v1",
        json_schema={
            "type": "object",
            "required": ["graph_ref", "graph_checksum", "stage_id"],
            "properties": {
                "graph_ref": {"type": "string"},
                "graph_checksum": {"type": "string"},
                "stage_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        current=True,
        authoritative_context_fields=(
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "stage_id",
        ),
    )
    catalog.register(registration)

    assert catalog.current_schema("graph_node_verified") == (
        "newsroom.graph-node-verified/v1"
    )
    assert catalog.validate(
        "graph_node_verified",
        "newsroom.graph-node-verified/v1",
        {
            "graph_ref": "research.paper-analysis@1",
            "graph_checksum": "sha256:" + "a" * 64,
            "stage_id": "run_research_rag",
        },
    )["stage_id"] == "run_research_rag"
    with pytest.raises(EventSchemaError):
        catalog.register(registration)
