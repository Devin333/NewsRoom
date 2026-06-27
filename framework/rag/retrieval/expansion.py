from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from framework.shared.json import to_jsonable


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class ExpansionMetadata:
    expanded_from_id: str
    reason: str
    edge: str
    rank: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expanded_from_id", _require_text(self.expanded_from_id, "expanded_from_id"))
        object.__setattr__(self, "reason", _require_text(self.reason, "reason"))
        object.__setattr__(self, "edge", _require_text(self.edge, "edge"))
        if self.rank < 0:
            raise ValueError("rank must be greater than or equal to zero")
        object.__setattr__(self, "rank", int(self.rank))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expanded_from_chunk_id": self.expanded_from_id,
            "expansion_reason": self.reason,
            "expansion_edge": self.edge,
            "expansion_rank": self.rank,
            **to_jsonable(dict(self.metadata)),
        }


def expansion_metadata(
    *,
    expanded_from_id: str,
    reason: str,
    edge: str,
    rank: int,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return ExpansionMetadata(
        expanded_from_id=expanded_from_id,
        reason=reason,
        edge=edge,
        rank=rank,
        metadata=metadata or {},
    ).to_dict()


__all__ = ["ExpansionMetadata", "expansion_metadata"]
