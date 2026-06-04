from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    scope: str = "default"
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 5
    context_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.query).strip():
            raise HarnessValidationError("query is required")
        if self.limit <= 0:
            raise HarnessValidationError("limit must be greater than zero")
        object.__setattr__(self, "query", str(self.query))
        object.__setattr__(self, "scope", str(self.scope))
        object.__setattr__(self, "filters", dict(self.filters))
        object.__setattr__(self, "context_refs", tuple(str(ref) for ref in self.context_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scope": self.scope,
            "filters": to_jsonable(self.filters),
            "limit": self.limit,
            "context_refs": list(self.context_refs),
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["RetrievalRequest"]
