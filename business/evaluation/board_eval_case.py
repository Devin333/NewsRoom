from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BoardEvalCase:
    case_id: str
    board_type: str
    topic: str
    signals: list[dict[str, Any]]
    expected_min_cards: int
    expected_tags: list[str] = field(default_factory=list)
    expected_entities: list[str] = field(default_factory=list)
    expected_quality_min: float = 0.0
    expected_subscription_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["BoardEvalCase"]
