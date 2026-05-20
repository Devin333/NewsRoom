from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.shared.ids import generate_id
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor: str | None = None
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: generate_id("audit"))
    occurred_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "actor": self.actor,
            "target": self.target,
            "payload": to_jsonable(self.payload),
            "occurred_at": format_datetime(self.occurred_at),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AuditEvent:
        occurred_at = parse_datetime(value.get("occurred_at")) or utc_now()
        return cls(
            event_id=str(value.get("event_id") or generate_id("audit")),
            action=str(value["action"]),
            actor=_optional_str(value.get("actor")),
            target=_optional_str(value.get("target")),
            payload=dict(value.get("payload") or {}),
            occurred_at=occurred_at,
            metadata=dict(value.get("metadata") or {}),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
