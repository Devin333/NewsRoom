from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class ApprovalsResource:
    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def list(self, status: str | None = None) -> JsonDict:
        return self.transport.request("GET", "/api/v1/approvals", params={"status": status})

    def get(self, approval_id: str) -> JsonDict:
        return self.transport.request("GET", f"/api/v1/approvals/{quote_path_segment(approval_id)}")

    def approve(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/approvals/{quote_path_segment(approval_id)}/approve",
            json={"decided_by": decided_by, "reason": reason},
        )

    def reject(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"/api/v1/approvals/{quote_path_segment(approval_id)}/reject",
            json={"decided_by": decided_by, "reason": reason},
        )
