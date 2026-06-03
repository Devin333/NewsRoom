from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.foundation.value_normalization import field_value, list_value


@dataclass(frozen=True)
class SourceGateEvidenceBundleView:
    items: tuple["SourceGateEvidenceItemView", ...]
    declared_item_count: int | None = None

    @classmethod
    def from_bundle(cls, evidence_bundle: Any) -> "SourceGateEvidenceBundleView":
        if isinstance(evidence_bundle, cls):
            return evidence_bundle
        return cls(
            items=tuple(
                SourceGateEvidenceItemView.from_item(item)
                for item in list_value(field_value(evidence_bundle, "items", default=[]))
            ),
            declared_item_count=_declared_item_count(field_value(evidence_bundle, "item_count")),
        )

    @property
    def item_count(self) -> int:
        if self.declared_item_count is not None:
            return self.declared_item_count
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
        metadata = _metadata_dict(field_value(item, "metadata", default={}))
        return cls(
            source_type=str(metadata.get("source_type") or "").strip().casefold(),
            category=normalize_source_gate_category(metadata.get("category")),
            source_url=str(field_value(item, "source_url", default="") or "").casefold(),
        )


def normalize_source_gate_category(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).casefold().replace("-", " ").replace("_", " ").split()).replace(" ", "_")


def _declared_item_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


__all__ = [
    "SourceGateEvidenceBundleView",
    "SourceGateEvidenceItemView",
    "normalize_source_gate_category",
]
