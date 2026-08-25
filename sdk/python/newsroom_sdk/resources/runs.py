from __future__ import annotations

from typing import Any

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class RunsResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def list(
        self,
        limit: int = 20,
        status: str | None = None,
        offset: int = 0,
        graph_id: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v2/graph-runs",
            params={
                "limit": limit,
                "offset": offset,
                "status": status,
                "graph_id": graph_id,
            },
        )

    def get(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v2/graph-runs/{quote_path_segment(run_id)}")

    def manifest(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v2/graph-runs/{quote_path_segment(run_id)}/manifest")

    def events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        node_instance_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v2/graph-runs/{quote_path_segment(run_id)}/events",
            params={
                "event_type": event_type,
                "node_instance_id": node_instance_id,
                "limit": limit,
                "offset": offset,
                "sequence_cursor": sequence_cursor,
            },
        )

    def runtime_status(
        self,
        run_id: str,
        *,
        node_id: str | None = None,
        node_instance_id: str | None = None,
        activity_id: str | None = None,
        attempt_id: str | None = None,
        child_id: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v2/graph-runs/{quote_path_segment(run_id)}/runtime/status",
            params={
                "node_id": node_id,
                "node_instance_id": node_instance_id,
                "activity_id": activity_id,
                "attempt_id": attempt_id,
                "child_id": child_id,
            },
        )

    def runtime_timeline(
        self,
        run_id: str,
        *,
        stream_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v2/graph-runs/{quote_path_segment(run_id)}/runtime/timeline",
            params={"stream_id": stream_id, "cursor": cursor, "limit": limit},
        )

    status = runtime_status
    timeline = runtime_timeline

    def artifacts(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v2/graph-runs/{quote_path_segment(run_id)}/artifacts")

    def artifact(self, run_id: str, artifact_key: str) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v2/graph-runs/{quote_path_segment(run_id)}/artifacts/{quote_path_segment(artifact_key)}",
        )

    def diagnostics(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v2/graph-runs/{quote_path_segment(run_id)}/diagnostics")

    def replay(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v2/graph-runs/{quote_path_segment(run_id)}/replay")

    def cancel(self, run_id: str, reason: str, cancellation_id: str | None = None) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v2/graph-runs/{quote_path_segment(run_id)}/cancel",
            json=_without_none({"reason_code": reason, "cancellation_id": cancellation_id}),
        )


def _without_none(payload: JsonDict) -> JsonDict:
    return {key: value for key, value in payload.items() if value is not None}
