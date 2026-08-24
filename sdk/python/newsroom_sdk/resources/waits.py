from __future__ import annotations

from newsroom_sdk.models import JsonDict
from newsroom_sdk.transport import HttpTransport, quote_path_segment


class WaitsResource:
    """Graph Wait operations exposed by the public SDK.

    The resource only submits bounded Wait causes. Harness owns durable
    validation, routing, and automatic resume after a cause is committed.
    """

    def __init__(self, transport: HttpTransport) -> None:
        self.transport = transport

    def inspect(self, run_id: str, node_instance_id: str) -> JsonDict:
        return self.transport.request(
            "GET",
            _wait_path(run_id, node_instance_id),
        )

    def deliver_signal(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        signal_id: str,
        signal_schema_ref: str,
        correlation: JsonDict,
        payload_ref: str,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"{_wait_path(run_id, node_instance_id)}/signals",
            json={
                "signal_id": signal_id,
                "signal_schema_ref": signal_schema_ref,
                "correlation": correlation,
                "payload_ref": payload_ref,
            },
        )

    def decide_approval(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        approval_id: str,
        approved: bool,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"{_wait_path(run_id, node_instance_id)}/approval",
            json={"approval_id": approval_id, "approved": approved},
        )

    def cancel(
        self,
        run_id: str,
        node_instance_id: str,
        *,
        cancellation_id: str,
        reason_code: str,
    ) -> JsonDict:
        return self.transport.request(
            "POST",
            f"{_wait_path(run_id, node_instance_id)}/cancel",
            json={
                "cancellation_id": cancellation_id,
                "reason_code": reason_code,
            },
        )


def _wait_path(run_id: str, node_instance_id: str) -> str:
    return (
        "/api/v2/graph-runs/"
        f"{quote_path_segment(run_id)}/waits/"
        f"{quote_path_segment(node_instance_id)}"
    )


__all__ = ["WaitsResource"]
