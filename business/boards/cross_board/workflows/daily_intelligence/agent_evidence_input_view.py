from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.foundation.models.source import Lineage
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem


@dataclass(frozen=True)
class DailyAgentEvidenceInputView:
    evidence_bundle: EvidenceBundle

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> "DailyAgentEvidenceInputView | None":
        bundle = evidence_bundle_from_agent_inputs(inputs)
        if bundle is None:
            return None
        return cls(evidence_bundle=bundle)

    @property
    def allowed_evidence_ids(self) -> set[str]:
        return {
            item.evidence_id
            for item in self.evidence_bundle.items
            if item.evidence_id
        }


def evidence_bundle_from_agent_inputs(inputs: dict[str, Any]) -> EvidenceBundle | None:
    for key in ("evidence_bundle", "bundle"):
        if key in inputs:
            return coerce_agent_evidence_bundle(inputs[key])
    request = inputs.get("request")
    if isinstance(request, dict):
        for key in ("evidence_bundle", "bundle"):
            if key in request:
                return coerce_agent_evidence_bundle(request[key])
    return None


def coerce_agent_evidence_bundle(value: Any) -> EvidenceBundle | None:
    if isinstance(value, EvidenceBundle):
        return value
    if not isinstance(value, dict):
        return None
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        return None
    items = []
    for item in raw_items:
        if isinstance(item, EvidenceItem):
            items.append(item)
        elif isinstance(item, dict):
            items.append(_evidence_item_from_payload(item))
    return EvidenceBundle(
        bundle_id=str(value.get("bundle_id") or "agent_input"),
        items=items,
        source_map={
            str(key): [str(source_item) for source_item in source_items]
            for key, source_items in dict(value.get("source_map") or {}).items()
        },
        missing_information=[
            str(item) for item in value.get("missing_information", []) if item
        ],
        coverage_notes=[str(item) for item in value.get("coverage_notes", []) if item],
        metadata=dict(value.get("metadata") or {}),
    )


def _evidence_item_from_payload(item: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=str(item.get("evidence_id") or ""),
        source_url=str(item.get("source_url") or ""),
        source_urls=[str(url) for url in item.get("source_urls", []) if url],
        title=str(item.get("title") or ""),
        summary=str(item.get("summary") or item.get("title") or ""),
        confidence=_float(item.get("confidence"), default=0.0),
        source_id=str(item.get("source_id") or ""),
        source_item_id=_optional_str(item.get("source_item_id")),
        source_item_ids=[str(value) for value in item.get("source_item_ids", []) if value],
        source_reliability=_optional_str(item.get("source_reliability")),
        publishable=bool(item.get("publishable", True)),
        evidence_type=str(item.get("evidence_type") or "other"),
        lineage=_lineage_from_payload(item.get("lineage")),
        metadata=dict(item.get("metadata") or {}),
    )


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _lineage_from_payload(value: Any) -> Lineage | None:
    if isinstance(value, Lineage):
        return value
    if isinstance(value, dict):
        try:
            return Lineage.from_dict(value)
        except Exception:
            return None
    return None


__all__ = [
    "DailyAgentEvidenceInputView",
    "coerce_agent_evidence_bundle",
    "evidence_bundle_from_agent_inputs",
]
