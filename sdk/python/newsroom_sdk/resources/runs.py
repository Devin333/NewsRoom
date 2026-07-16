from __future__ import annotations

from typing import Any

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class RunsResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def create(self, workflow_id: str, **kwargs: Any) -> JsonDict:
        return self.transport.request(
            "POST",
            "/api/v1/runs",
            json=_without_none({"workflow_id": workflow_id, **kwargs}),
        )

    def list(
        self,
        limit: int = 20,
        status: str | None = None,
        offset: int = 0,
        workflow_id: str | None = None,
        profile: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/runs",
            params={
                "limit": limit,
                "offset": offset,
                "status": status,
                "workflow_id": workflow_id,
                "profile": profile,
            },
        )

    def get(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/runs/{quote_path_segment(run_id)}")

    def manifest(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/runs/{quote_path_segment(run_id)}/manifest")

    def events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        step_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/runs/{quote_path_segment(run_id)}/events",
            params={
                "event_type": event_type,
                "step_id": step_id,
                "limit": limit,
                "offset": offset,
                "sequence_cursor": sequence_cursor,
            },
        )

    def artifacts(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/runs/{quote_path_segment(run_id)}/artifacts")

    def artifact(self, run_id: str, artifact_key: str) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/runs/{quote_path_segment(run_id)}/artifacts/{quote_path_segment(artifact_key)}",
        )

    def diagnostics(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/runs/{quote_path_segment(run_id)}/diagnostics")

    def replay(self, run_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/runs/{quote_path_segment(run_id)}/replay")

    def cancel(self, run_id: str, reason: str, actor_id: str | None = None) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/runs/{quote_path_segment(run_id)}/operations/cancel",
            json=_without_none({"reason": reason, "actor_id": actor_id}),
        )


def _without_none(payload: JsonDict) -> JsonDict:
    return {key: value for key, value in payload.items() if value is not None}
