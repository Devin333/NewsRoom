from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceGateEvidenceBundleView:
    items: tuple["SourceGateEvidenceItemView", ...]

    @classmethod
    def from_bundle(cls, evidence_bundle: Any) -> "SourceGateEvidenceBundleView":
        if isinstance(evidence_bundle, cls):
            return evidence_bundle
        return cls(
            items=tuple(
                SourceGateEvidenceItemView.from_item(item)
                for item in getattr(evidence_bundle, "items", []) or []
            )
        )

    @property
    def item_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class SourceGateEvidenceItemView:
    source_type: str
    category: str | None
    source_url: str

    @classmethod
    def from_item(cls, item: Any) -> "SourceGateEvidenceItemView":
        if isinstance(item, cls):
            return item
        metadata = dict(getattr(item, "metadata", {}) or {})
        return cls(
            source_type=str(metadata.get("source_type") or "").strip().casefold(),
            category=normalize_source_gate_category(metadata.get("category")),
            source_url=str(getattr(item, "source_url", "") or "").casefold(),
        )


def normalize_source_gate_category(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).casefold().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


__all__ = [
    "SourceGateEvidenceBundleView",
    "SourceGateEvidenceItemView",
    "normalize_source_gate_category",
]
