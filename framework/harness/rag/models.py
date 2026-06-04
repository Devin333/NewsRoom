from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.retrieval.evidence_pack import EvidencePack
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class RAGContextPack:
    pack_id: str
    query: str
    evidence: tuple[EvidencePack, ...]
    context_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.pack_id).strip():
            raise HarnessValidationError("pack_id is required")
        if not str(self.query).strip():
            raise HarnessValidationError("query is required")
        if not all(isinstance(item, EvidencePack) for item in self.evidence):
            raise HarnessValidationError("evidence must be EvidencePack values")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "context_refs", tuple(str(ref) for ref in self.context_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "query": self.query,
            "evidence": [item.to_dict() for item in self.evidence],
            "context_refs": list(self.context_refs),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class RAGSessionRequest:
    query: str
    context_refs: tuple[str, ...] = ()
    max_rounds: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.query).strip():
            raise HarnessValidationError("query is required")
        if self.max_rounds <= 0:
            raise HarnessValidationError("max_rounds must be greater than zero")
        object.__setattr__(self, "context_refs", tuple(str(ref) for ref in self.context_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "context_refs": list(self.context_refs),
            "max_rounds": self.max_rounds,
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["RAGContextPack", "RAGSessionRequest"]
