from __future__ import annotations

from typing import Any

from framework.governance.audit.event import AuditEvent
from framework.governance.audit.store import AuditStore, InMemoryAuditStore


class AuditRecorder:
    def __init__(self, store: AuditStore | None = None) -> None:
        self.store = store or InMemoryAuditStore()

    def record(
        self,
        action: str,
        actor: str | None = None,
        target: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            actor=actor,
            target=target,
            payload=dict(payload or {}),
        )
        self.store.append(event)
        return event

    def list_events(self) -> list[AuditEvent]:
        return self.store.list()
