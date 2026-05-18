from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class ReportsResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def latest(self) -> JsonDict:
        return self.transport.request("GET", "/api/v1/reports/latest")

    def list(
        self,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_family: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/reports",
            params={
                "limit": limit,
                "workflow_id": workflow_id,
                "workflow_family": workflow_family,
            },
        )

    def get(self, report_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/reports/{quote_path_segment(report_id)}")

    def markdown(self, report_id: str) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/reports/{quote_path_segment(report_id)}/markdown",
        )

    def quality(self, report_id: str) -> JsonDict:
        return self.transport.request(
            "GET",
            f"/api/v1/reports/{quote_path_segment(report_id)}/quality",
        )

    def search(self, query: str, limit: int = 20) -> JsonDict:
        return self.transport.request(
            "GET",
            "/api/v1/search/reports",
            params={"q": query, "limit": limit},
        )
