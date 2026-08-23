from interfaces.api.app import create_app
from interfaces.api.openapi import export_openapi_schema


def test_openapi_declares_graph_run_paths_and_graph_models_only() -> None:
    schema = export_openapi_schema(create_app(audit_emitter_factory=None))
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v2/graph-runs" in paths
    assert "/api/v2/graph-runs/{run_id}/events" in paths
    assert "/api/v2/graph-runs/{run_id}/events/stream" in paths
    assert "/api/v2/graph-runs/{run_id}/cancel" in paths
    assert "/api/v1/runs" not in paths
    assert "GraphRunListItem" in schemas
    assert "GraphRunDetail" in schemas
    assert "RunListItem" not in schemas
    assert "RunDetail" not in schemas
    assert "workflow_id" not in schemas["GraphRunListItem"]["properties"]
    assert "graph_id" in schemas["GraphRunListItem"]["properties"]


def test_openapi_marks_graph_event_stream_as_sse_and_events_as_run_event_data() -> None:
    schema = export_openapi_schema(create_app(audit_emitter_factory=None))
    event_response = schema["paths"]["/api/v2/graph-runs/{run_id}/events"]["get"]["responses"]["200"]
    stream_response = schema["paths"]["/api/v2/graph-runs/{run_id}/events/stream"]["get"]["responses"]["200"]

    assert event_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunEventsApiResponse"
    }
    assert "text/event-stream" in stream_response["content"]
    assert "application/json" not in stream_response["content"]
