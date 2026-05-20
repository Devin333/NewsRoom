from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from framework.governance.audit.event import AuditEvent
from framework.shared.time import parse_datetime


class AuditStore(Protocol):
    def append(self, event: AuditEvent) -> None: ...

    def list(self, filters: dict[str, Any] | None = None) -> list[AuditEvent]: ...


class InMemoryAuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list(self, filters: dict[str, Any] | None = None) -> list[AuditEvent]:
        return [event for event in self._events if _matches(event, filters or {})]

    def clear(self) -> None:
        self._events.clear()


def _matches(event: AuditEvent, filters: dict[str, Any]) -> bool:
    for field in ("action", "actor", "target"):
        value = filters.get(field)
        if value is not None and getattr(event, field) != value:
            return False
    since = _filter_datetime(filters.get("since"))
    if since is not None and event.occurred_at < since:
        return False
    until = _filter_datetime(filters.get("until"))
    if until is not None and event.occurred_at > until:
        return False
    return True


def _filter_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return parse_datetime(value)
    return parse_datetime(str(value))
