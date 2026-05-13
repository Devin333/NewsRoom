from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from interfaces.models.actor import ActorContext


AuditResult = Literal["succeeded", "failed", "blocked"]


class AuditRecord(BaseModel):
    audit_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex}")
    actor: ActorContext
    action: str
    resource_type: str
    resource_id: str | None = None
    result: AuditResult
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump() if hasattr(self, "model_dump") else self.dict()
        payload["timestamp"] = self.timestamp.isoformat().replace("+00:00", "Z")
        return payload
