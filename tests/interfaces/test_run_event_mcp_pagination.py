from __future__ import annotations

from interfaces.services.mcp_service import MCPApplicationService
from interfaces.services.run_inspection_service import RunEventsResult


def test_mcp_run_events_schema_and_call_preserve_cursor() -> None:
    service = _CapturingInspectionService()
    mcp = MCPApplicationService(
        graph_run_inspection_service_factory=lambda: service
    )
    tools = {tool.name: tool for tool in mcp.catalog().tools}

    schema = tools["news.run.events"].input_schema
    assert {
        "limit",
        "offset",
        "event_type",
        "node_instance_id",
        "sequence_cursor",
    } <= set(schema["properties"])

    result = mcp.call_tool(
        "news.run.events",
        {
            "run_id": "run-1",
            "limit": 1,
            "event_type": "step_started",
            "node_instance_id": "node-7",
            "sequence_cursor": "opaque-cursor",
        },
    )

    assert result.success is True
    assert service.calls[0]["sequence_cursor"] == "opaque-cursor"
    assert result.data["next_sequence_cursor"] == "next-cursor"


def test_mcp_run_events_resource_continues_with_query_cursor() -> None:
    service = _CapturingInspectionService()
    mcp = MCPApplicationService(
        graph_run_inspection_service_factory=lambda: service
    )
    uri = (
        "news://runs/run-1/events?limit=1&event_type=step_started"
        "&node_instance_id=node-7&sequence_cursor=opaque-cursor"
    )

    result = mcp.read_resource(uri)

    assert result.success is True
    assert service.calls == [
        {
            "run_id": "run-1",
            "limit": 1,
            "offset": 0,
            "event_type": "step_started",
            "node_instance_id": "node-7",
            "sequence_cursor": "opaque-cursor",
        }
    ]
    assert result.data["next_sequence_cursor"] == "next-cursor"


def test_mcp_run_events_preserves_explicit_unavailable_metadata() -> None:
    mcp = MCPApplicationService(
        graph_run_inspection_service_factory=_UnavailableMetadataInspectionService
    )

    tool_result = mcp.call_tool("news.run.events", {"run_id": "run-1"})
    resource_result = mcp.read_resource("news://runs/run-1/events")

    for result in (tool_result, resource_result):
        assert result.success is True
        assert result.data["availability"] == "unavailable"
        assert result.data["source"] == "projection"
        assert result.data["projection_status"] == "stale"
        assert result.data["unavailable_reason_class"] == "EventStoreUnavailableError"


class _CapturingInspectionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_run_events(self, run_id: str, **kwargs):
        self.calls.append({"run_id": run_id, **kwargs})
        return RunEventsResult(
            run_id=run_id,
            events=[
                {
                    "event_type": "step_started",
                    "stream_sequence": 7,
                    "node_instance_id": "node-7",
                    "payload": {},
                }
            ],
            events_path=".newsroom/runs/run-1/events.jsonl",
            next_sequence_cursor="next-cursor",
            high_watermark=9,
            source="durable_store",
            projection_status="stale",
            projection_checksum="sha256:" + "a" * 64,
            projection_high_watermark=7,
            availability="available",
        )


class _UnavailableMetadataInspectionService:
    def get_run_events(self, run_id: str, **kwargs):
        return RunEventsResult(
            run_id=run_id,
            events=[],
            events_path=".newsroom/runs/run-1/events.jsonl",
            source="projection",
            projection_status="stale",
            availability="unavailable",
            unavailable_reason_class="EventStoreUnavailableError",
        )
