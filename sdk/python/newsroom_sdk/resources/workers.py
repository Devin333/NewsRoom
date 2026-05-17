from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class WorkersResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def status(self, stale_after_seconds: int = 60) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/workers",
            params={"stale_after_seconds": stale_after_seconds},
        )

    def get(self, worker_id: str, stale_after_seconds: int = 60) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/workers/{quote_path_segment(worker_id)}",
            params={"stale_after_seconds": stale_after_seconds},
        )

    def queues(self, queue_names: list[str] | None = None) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/queues",
            params={"queue_name": queue_names or []},
        )
