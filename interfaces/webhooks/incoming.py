from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from interfaces.webhooks.signatures import verify_signature


@dataclass(frozen=True)
class IncomingWebhookEvent:
    event_type: str
    payload: dict[str, Any]
    provider: str = "generic"
    delivery_id: str | None = None
    signature_verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "provider": self.provider,
            "delivery_id": self.delivery_id,
            "signature_verified": self.signature_verified,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
        }


class IncomingWebhookHandler:
    def __init__(
        self,
        *,
        secret: str | None = None,
        worker_service: Any | None = None,
    ) -> None:
        self.secret = secret
        self.worker_service = worker_service

    def parse(
        self,
        body: bytes,
        *,
        event_type: str,
        provider: str = "generic",
        delivery_id: str | None = None,
        signature_header: str | None = None,
    ) -> IncomingWebhookEvent:
        signature_verified = False
        if self.secret is not None:
            signature_verified = verify_signature(body, self.secret, signature_header)
            if not signature_verified:
                raise PermissionError("invalid webhook signature")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("webhook payload must be a JSON object")
        return IncomingWebhookEvent(
            event_type=event_type,
            provider=provider,
            delivery_id=delivery_id,
            signature_verified=signature_verified,
            payload=payload,
        )

    def handle(self, event: IncomingWebhookEvent) -> dict[str, Any]:
        if event.event_type == "manual.memory_reindex":
            worker = self._require_worker_service()
            run_id = str(event.payload.get("run_id") or "")
            if not run_id:
                raise ValueError("run_id is required for manual.memory_reindex")
            result = worker.enqueue_memory_reindex(
                run_id=run_id,
                topic=event.payload.get("topic"),
                queue_name=str(event.payload.get("queue_name") or "news:queue:memory"),
            )
            return {
                "event_type": event.event_type,
                "handled": True,
                "action": "enqueue_memory_reindex",
                "result": result.to_dict(),
            }
        if event.event_type == "manual.source_health_check":
            worker = self._require_worker_service()
            result = worker.enqueue_source_health_check(
                source_id=event.payload.get("source_id"),
                include_disabled=bool(event.payload.get("include_disabled", False)),
                limit=event.payload.get("limit"),
                force=bool(event.payload.get("force", False)),
                queue_name=str(event.payload.get("queue_name") or "news:queue:sources"),
            )
            return {
                "event_type": event.event_type,
                "handled": True,
                "action": "enqueue_source_health_check",
                "result": result.to_dict(),
            }
        if event.event_type in {"source.notification", "github.release"}:
            worker = self._require_worker_service()
            result = worker.enqueue_source_health_check(
                source_id=event.payload.get("source_id"),
                include_disabled=bool(event.payload.get("include_disabled", False)),
                limit=event.payload.get("limit"),
                force=bool(event.payload.get("force", False)),
                queue_name=str(event.payload.get("queue_name") or "news:queue:sources"),
            )
            return {
                "event_type": event.event_type,
                "handled": True,
                "action": "enqueue_source_health_check",
                "result": result.to_dict(),
            }
        return {
            "event_type": event.event_type,
            "handled": False,
            "action": None,
            "result": None,
        }

    def _require_worker_service(self) -> Any:
        if self.worker_service is None:
            from interfaces.services.worker_service import WorkerApplicationService

            self.worker_service = WorkerApplicationService()
        return self.worker_service
