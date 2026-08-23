from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from interfaces.api import create_app
from interfaces.api.app import _run_events_sse_frames, _run_progress_sse_frames
from interfaces.api.openapi import export_openapi_schema
from interfaces.cli import news as news_cli
from interfaces.cli.commands import runs as run_commands
from interfaces.services.run_inspection_service import RunEventsResult
from framework.events.errors import EventStoreUnavailableError


def test_api_run_events_forwards_sequence_cursor_and_filters() -> None:
    service = _CapturingInspectionService()
    client = TestClient(
        create_app(
            graph_run_inspection_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )

    response = client.get(
        "/api/v2/graph-runs/run-1/events",
        params={
            "event_type": "step_started",
            "node_instance_id": "node-7",
            "limit": 1,
            "sequence_cursor": "opaque-cursor",
        },
    )

    assert response.status_code == 200
    assert service.calls == [
        {
            "run_id": "run-1",
            "event_type": "step_started",
            "node_instance_id": "node-7",
            "limit": 1,
            "offset": 0,
            "sequence_cursor": "opaque-cursor",
        }
    ]
    data = response.json()["data"]
    assert data["source"] == "durable_store"
    assert data["next_sequence_cursor"] == "next-cursor"
    assert data["projection_status"] == "stale"


def test_cli_run_events_forwards_cursor_and_prints_availability(
    monkeypatch,
    capsys,
) -> None:
    service = _CapturingInspectionService()
    monkeypatch.setattr(
        run_commands,
        "graph_run_inspection_service_from_env",
        lambda **kwargs: service,
    )

    exit_code = news_cli.main(
        [
            "runs",
            "events",
            "run-1",
            "--limit",
            "1",
            "--event-type",
            "step_started",
            "--node-instance-id",
            "node-7",
            "--sequence-cursor",
            "opaque-cursor",
        ]
    )

    assert exit_code == 0
    assert service.calls[0]["sequence_cursor"] == "opaque-cursor"
    output = capsys.readouterr().out
    assert "source=durable_store" in output
    assert "availability=available" in output
    assert "next_sequence_cursor=next-cursor" in output


def test_sse_frames_use_durable_sequence_ids_and_done_metadata() -> None:
    payload = _result().to_dict()
    payload["events"][0]["sse_resume_cursor"] = "resume-cursor-7"
    payload["sse_resume_cursor"] = "resume-cursor-7"

    api_frames = "".join(_run_events_sse_frames(payload))
    cli_frames = "".join(run_commands.run_events_sse_frames(payload))
    progress_frames = "".join(_run_progress_sse_frames(payload))

    for frames in (api_frames, cli_frames, progress_frames):
        assert "id: resume-cursor-7\n" in frames
        assert '"sequence": 7' in frames
        assert '"high_watermark": 9' in frames
        assert '"next_sequence_cursor": "next-cursor"' in frames
        assert '"projection_status": "stale"' in frames
        assert '"projection_high_watermark": 7' in frames
        assert '"projection_checksum": "sha256:' in frames
        assert '"sse_resume_cursor": "resume-cursor-7"' in frames


def test_api_sse_uses_last_event_id_and_rejects_query_cursor_conflict() -> None:
    service = _CapturingInspectionService()
    client = TestClient(
        create_app(
            graph_run_inspection_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )

    response = client.get(
        "/api/v2/graph-runs/run-1/events/stream",
        headers={"Last-Event-ID": "resume-cursor-7"},
    )
    assert response.status_code == 200
    assert service.sse_calls == [
        {
            "run_id": "run-1",
            "limit": None,
            "sequence_cursor": None,
            "last_event_id": "resume-cursor-7",
        },
    ]

    conflict = client.get(
        "/api/v2/graph-runs/run-1/events/stream?sequence_cursor=snapshot-cursor",
        headers={"Last-Event-ID": "resume-cursor-7"},
    )
    assert conflict.status_code == 400
    assert conflict.json()["error"]["code"] == "invalid_graph_run_events_request"
def test_api_maps_disabled_projection_fallback_to_retryable_503() -> None:
    client = TestClient(
        create_app(
            graph_run_inspection_service_factory=_UnavailableInspectionService,
            audit_emitter_factory=None,
        )
    )

    for endpoint in (
        "/api/v2/graph-runs/run-1/events",
        "/api/v2/graph-runs/run-1/events/stream",
    ):
        response = client.get(endpoint)
        assert response.status_code == 503
        payload = response.json()
        assert payload["error"]["code"] == "event_store_unavailable"
        assert payload["error"]["retryable"] is True


def test_cli_maps_disabled_projection_fallback_to_exit_code_two(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        run_commands,
        "graph_run_inspection_service_from_env",
        lambda **kwargs: _UnavailableInspectionService(),
    )

    exit_code = news_cli.main(["runs", "events", "run-1"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "availability=unavailable" in captured.err
    assert "EventStoreUnavailableError" in captured.err


def test_projection_fallback_sse_does_not_emit_durable_event_id() -> None:
    payload = RunEventsResult(
        run_id="run-1",
        events=[{"event_type": "step_started", "payload": {}}],
        events_path=".newsroom/runs/run-1/events.jsonl",
        source="projection",
        projection_status="stale",
        availability="unavailable",
        unavailable_reason_class="EventStoreUnavailableError",
    ).to_dict()

    assert "id:" not in "".join(_run_events_sse_frames(payload))
    assert "id:" not in "".join(_run_progress_sse_frames(payload))


def test_openapi_run_events_has_typed_metadata_envelope() -> None:
    schema = export_openapi_schema()
    response = schema["paths"]["/api/v2/graph-runs/{run_id}/events"]["get"]["responses"]["200"]

    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunEventsApiResponse"
    }
    properties = schema["components"]["schemas"]["RunEventsData"]["properties"]
    assert {
        "run_id",
        "event_count",
        "events",
        "events_path",
        "next_sequence_cursor",
        "high_watermark",
        "source",
        "projection_status",
        "projection_checksum",
        "projection_high_watermark",
        "availability",
        "unavailable_reason_class",
    } <= set(properties)


def test_run_event_result_rejects_contradictory_availability_metadata() -> None:
    with pytest.raises(ValueError, match="durable_store"):
        RunEventsResult(
            run_id="run-1",
            events=[],
            events_path=None,
            source="projection",
            availability="available",
        )
    with pytest.raises(ValueError, match="reason class"):
        RunEventsResult(
            run_id="run-1",
            events=[],
            events_path=None,
            source="projection",
            availability="unavailable",
            projection_status="stale",
        )


class _CapturingInspectionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sse_calls: list[dict] = []

    def get_run_events(self, run_id: str, **kwargs):
        self.calls.append({"run_id": run_id, **kwargs})
        return _result()

    def get_run_events_for_sse(self, run_id: str, **kwargs):
        self.sse_calls.append({"run_id": run_id, **kwargs})
        if kwargs.get("sequence_cursor") and kwargs.get("last_event_id"):
            raise ValueError("sequence_cursor and Last-Event-ID cannot be combined")
        result = _result()
        event = dict(result.events[0])
        event["sse_resume_cursor"] = "resume-cursor-7"
        return replace(
            result,
            events=[event],
            sse_resume_cursor="resume-cursor-7",
        )


class _UnavailableInspectionService:
    def get_run_events(self, run_id: str, **kwargs):
        raise EventStoreUnavailableError("durable event store is unavailable")

    def get_run_events_for_sse(self, run_id: str, **kwargs):
        raise EventStoreUnavailableError("durable event store is unavailable")


def _result() -> RunEventsResult:
    return RunEventsResult(
        run_id="run-1",
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
