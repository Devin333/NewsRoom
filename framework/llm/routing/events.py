from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Callable

from framework.llm.redaction import redact_sensitive_values
from framework.shared.graph_identity import GraphExecutionIdentity


@dataclass(frozen=True)
class LLMRouterEvent:
    event_type: str
    route_id: str
    deployment_id: str | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    execution_identity: GraphExecutionIdentity | None = None

    def __post_init__(self) -> None:
        if self.execution_identity is not None and not isinstance(
            self.execution_identity,
            GraphExecutionIdentity,
        ):
            object.__setattr__(
                self,
                "execution_identity",
                GraphExecutionIdentity.from_dict(self.execution_identity),
            )

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_type": self.event_type,
            "route_id": self.route_id,
            "deployment_id": self.deployment_id,
            "provider": self.provider,
            "model": self.model,
            "metadata": dict(self.metadata),
            "occurred_at": _datetime_to_json(self.occurred_at),
            "execution_identity": (
                self.execution_identity.to_dict()
                if self.execution_identity is not None
                else None
            ),
        }
        if redact:
            return redact_sensitive_values(payload)
        return payload


LLMRouterEventSink = Callable[[LLMRouterEvent], None]


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")
