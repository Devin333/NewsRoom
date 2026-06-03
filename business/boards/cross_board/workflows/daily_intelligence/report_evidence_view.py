from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.source_gate_evidence import (
    SourceGateEvidenceBundleView,
)
from business.foundation.value_normalization import field_value, list_value


@dataclass(frozen=True)
class ReportEvidenceItemView:
    title: str
    summary: str
    source_url: str
    payload: dict[str, Any]

    @classmethod
    def from_item(cls, item: Any) -> "ReportEvidenceItemView":
        return cls(
            title=str(field_value(item, "title", default="") or ""),
            summary=str(field_value(item, "summary", default="") or ""),
            source_url=str(field_value(item, "source_url", default="") or ""),
            payload=_item_payload(item),
        )


@dataclass(frozen=True)
class ReportEvidenceDraftView:
    items: tuple[ReportEvidenceItemView, ...]
    source_urls: tuple[str, ...]
    item_count: int

    @classmethod
    def from_bundle(cls, evidence_bundle: Any) -> "ReportEvidenceDraftView":
        items = tuple(
            ReportEvidenceItemView.from_item(item)
            for item in list_value(field_value(evidence_bundle, "items", default=[]))
        )
        source_urls = _source_urls(evidence_bundle, items)
        return cls(
            items=items,
            source_urls=source_urls,
            item_count=SourceGateEvidenceBundleView.from_bundle(evidence_bundle).item_count,
        )

    @property
    def lead(self) -> ReportEvidenceItemView:
        if not self.items:
            raise ValueError("report evidence view requires at least one evidence item")
        return self.items[0]

    @property
    def payload(self) -> list[dict[str, Any]]:
        return [dict(item.payload) for item in self.items]


def _item_payload(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        payload = item.to_dict()
        return dict(payload) if isinstance(payload, dict) else {"value": payload}
    if isinstance(item, dict):
        return dict(item)
    return {
        "title": field_value(item, "title"),
        "summary": field_value(item, "summary"),
        "source_url": field_value(item, "source_url"),
    }


def _source_urls(
    evidence_bundle: Any,
    items: tuple[ReportEvidenceItemView, ...],
) -> tuple[str, ...]:
    explicit_urls = {
        str(url)
        for url in list_value(field_value(evidence_bundle, "source_urls", default=[]))
        if url
    }
    if explicit_urls:
        return tuple(sorted(explicit_urls))
    return tuple(sorted({item.source_url for item in items if item.source_url}))


__all__ = ["ReportEvidenceDraftView", "ReportEvidenceItemView"]
