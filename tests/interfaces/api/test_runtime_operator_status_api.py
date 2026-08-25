from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from framework.events.runtime.projection import (
    RuntimeEventCursor,
    RuntimeEventEnvelope,
    RuntimeEventIdentity,
    RuntimeEventPage,
    RuntimeEventType,
    RuntimeStatus,
)
from framework.shared.graph_identity import GraphExecutionIdentity
from interfaces.api import create_app


def _graph_identity(run_id: str) -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id=run_id,
        graph_id="graph",
        graph_version="1.0.0",
        graph_ref="graph@1.0.0",
        graph_checksum="sha256:" + "a" * 64,
        node_id="node-1",
        node_instance_id="node-1-1",
        activity_id="activity-1",
        attempt=1,
    )


class _FakeRuntimeOperatorService:
    def __init__(self) -> None:
        self.status_calls: list[dict] = []
        self.timeline_calls: list[dict] = []

    def get_status(self, **kwargs):
        self.status_calls.append(kwargs)
        return (
            RuntimeStatus(
                identity=RuntimeEventIdentity(
                    graph_identity=_graph_identity("run-1"),
                    node_id="node-1",
                    node_instance_id="node-1-1",
                    activity_id="activity-1",
                    attempt_id="attempt-1",
                ),
                status="running",
                reason_code=None,
                last_event_id="event-1",
                sequence=1,
                updated_at=datetime(2026, 8, 26, tzinfo=UTC),
                refs=("child-1",),
            ),
        )

    def get_timeline(self, **kwargs):
        self.timeline_calls.append(kwargs)
        event = RuntimeEventEnvelope(
            event_id="event-1",
            event_type=RuntimeEventType.CHILD_STATUS,
            occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
            identity=RuntimeEventIdentity(node_id="node-1"),
            status="running",
            stream_id=kwargs["stream_id"],
        )
        cursor = RuntimeEventCursor(kwargs["stream_id"], 1, "sha256:" + "a" * 64)
        return RuntimeEventPage(events=(event,), cursor=cursor, has_more=False)


def test_runtime_operator_queries_are_read_only_and_forward_filters() -> None:
    service = _FakeRuntimeOperatorService()
    client = TestClient(
        create_app(
            runtime_operator_status_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )

    status = client.get(
        "/api/v2/graph-runs/run-1/runtime/status",
        params={
            "node_id": "node-1",
            "node_instance_id": "node-1-1",
            "activity_id": "activity-1",
            "attempt_id": "attempt-1",
            "child_id": "child-1",
        },
    )
    assert status.status_code == 200
    assert status.json()["data"]["run_id"] == "run-1"
    assert status.json()["data"]["statuses"][0]["status"] == "running"
    assert service.status_calls == [
        {
            "run_id": "run-1",
            "node_id": "node-1",
            "node_instance_id": "node-1-1",
            "activity_id": "activity-1",
            "attempt_id": "attempt-1",
            "child_id": "child-1",
        }
    ]

    timeline = client.get(
        "/api/v2/graph-runs/run-1/runtime/timeline",
        params={"cursor": "run-1:0:sha256:" + "b" * 64, "limit": 2},
    )
    assert timeline.status_code == 200
    assert timeline.json()["data"]["stream_id"] == "run-1"
    assert timeline.json()["data"]["cursor"] == "run-1:1:sha256:" + "a" * 64
    assert service.timeline_calls == [
        {
            "stream_id": "run-1",
            "cursor": "run-1:0:sha256:" + "b" * 64,
            "limit": 2,
        }
    ]

    assert client.post("/api/v2/graph-runs/run-1/runtime/status").status_code == 405


def test_runtime_operator_queries_fail_closed_without_projection() -> None:
    client = TestClient(create_app(audit_emitter_factory=None))
    response = client.get("/api/v2/graph-runs/run-1/runtime/status")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "runtime_projection_unavailable"


def test_runtime_timeline_rejects_cross_run_stream() -> None:
    service = _FakeRuntimeOperatorService()
    client = TestClient(
        create_app(
            runtime_operator_status_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )
    response = client.get(
        "/api/v2/graph-runs/run-1/runtime/timeline",
        params={"stream_id": "run-2"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "runtime_stream_run_mismatch"
    assert service.timeline_calls == []


def test_runtime_operator_rejects_cross_run_projection_results() -> None:
    class CrossRunService(_FakeRuntimeOperatorService):
        def get_status(self, **kwargs):
            return (
                RuntimeStatus(
                    identity=RuntimeEventIdentity(graph_identity=_graph_identity("run-2")),
                    status="running",
                    reason_code=None,
                    last_event_id="event-cross-run",
                    sequence=1,
                    updated_at=datetime(2026, 8, 26, tzinfo=UTC),
                ),
            )

        def get_timeline(self, **kwargs):
            event = RuntimeEventEnvelope(
                event_id="event-cross-run",
                event_type=RuntimeEventType.CHILD_STATUS,
                occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
                identity=RuntimeEventIdentity(graph_identity=_graph_identity("run-2")),
                status="running",
                stream_id=kwargs["stream_id"],
            )
            return RuntimeEventPage(
                events=(event,),
                cursor=None,
                has_more=False,
            )

    service = CrossRunService()
    client = TestClient(
        create_app(
            runtime_operator_status_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )
    status = client.get("/api/v2/graph-runs/run-1/runtime/status")
    assert status.status_code == 409
    assert status.json()["error"]["code"] == "runtime_projection_identity_conflict"
    timeline = client.get("/api/v2/graph-runs/run-1/runtime/timeline")
    assert timeline.status_code == 409
    assert timeline.json()["error"]["code"] == "runtime_projection_identity_conflict"


def test_runtime_timeline_limit_is_bounded_at_the_route() -> None:
    service = _FakeRuntimeOperatorService()
    client = TestClient(
        create_app(
            runtime_operator_status_service_factory=lambda: service,
            audit_emitter_factory=None,
        )
    )
    assert client.get(
        "/api/v2/graph-runs/run-1/runtime/timeline",
        params={"limit": 0},
    ).status_code == 422
    assert client.get(
        "/api/v2/graph-runs/run-1/runtime/timeline",
        params={"limit": 1001},
    ).status_code == 422
