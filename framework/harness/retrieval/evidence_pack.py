from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True)
class EvidencePack:
    evidence_id: str
    title: str
    summary: str
    source_refs: tuple[str, ...]
    confidence: float
    freshness: str
    lineage: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.evidence_id).strip():
            raise HarnessValidationError("evidence_id is required")
        if not str(self.title).strip():
            raise HarnessValidationError("title is required")
        if not str(self.summary).strip():
            raise HarnessValidationError("summary is required")
        if not self.source_refs:
            raise HarnessValidationError("source_refs are required")
        if not 0 <= self.confidence <= 1:
            raise HarnessValidationError("confidence must be between 0 and 1")
        if not str(self.freshness).strip():
            raise HarnessValidationError("freshness is required")
        if not self.lineage:
            raise HarnessValidationError("lineage is required")
        object.__setattr__(self, "evidence_id", str(self.evidence_id))
        object.__setattr__(self, "title", str(self.title))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(self, "source_refs", tuple(str(ref) for ref in self.source_refs))
        object.__setattr__(self, "freshness", str(self.freshness))
        object.__setattr__(self, "lineage", tuple(str(item) for item in self.lineage))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "summary": self.summary,
            "source_refs": list(self.source_refs),
            "confidence": self.confidence,
            "freshness": self.freshness,
            "lineage": list(self.lineage),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class EvidencePackCollection:
    packs: tuple[EvidencePack, ...]
    request_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(isinstance(pack, EvidencePack) for pack in self.packs):
            raise HarnessValidationError("packs must be EvidencePack values")
        object.__setattr__(self, "packs", tuple(self.packs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "packs": [pack.to_dict() for pack in self.packs],
            "request_ref": self.request_ref,
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["EvidencePack", "EvidencePackCollection"]
