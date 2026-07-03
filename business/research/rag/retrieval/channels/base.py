from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RankedHit:
    chunk_id: str
    score: float
    channel: str
    metadata: dict[str, Any] = field(default_factory=dict)


RankedList = list[RankedHit]


class RecallChannel(Protocol):
    name: str

    def recall(self, request: Any, plan: Any) -> RankedList: ...


__all__ = ["RankedHit", "RankedList", "RecallChannel"]
