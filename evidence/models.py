from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_url: str
    title: str
    summary: str
    confidence: float
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "title": self.title,
            "summary": self.summary,
            "confidence": self.confidence,
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    items: list[EvidenceItem]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_urls(self) -> set[str]:
        return {item.source_url for item in self.items}

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "items": [item.to_dict() for item in self.items],
            "metadata": dict(self.metadata),
        }
