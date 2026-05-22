from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubscriptionTarget:
    board_type: str
    topic: str | None
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    priority: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubscriptionPayload:
    run_id: str
    board_type: str
    topic: str | None
    targets: list[SubscriptionTarget] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    quality_score: float | None = None
    delivery_hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "board_type": self.board_type,
            "topic": self.topic,
            "targets": [target.to_dict() for target in self.targets],
            "cards": list(self.cards),
            "summary": self.summary,
            "quality_score": self.quality_score,
            "delivery_hints": dict(self.delivery_hints),
        }


@dataclass(frozen=True)
class DeliveryPlan:
    payload_id: str
    channels: list[str]
    priority: str
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["DeliveryPlan", "SubscriptionPayload", "SubscriptionTarget"]
