from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel, Signal


class BoardEvidenceBundle(PrimitiveModel):
    refs: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


class BoardEvidenceAssemblyService:
    def build(
        self,
        signals: list[Signal],
        *,
        extracted_entities: list[dict[str, Any]],
    ) -> BoardEvidenceBundle:
        entities_by_signal = {
            item.get("signal_id"): item.get("entities", [])
            for item in extracted_entities
            if isinstance(item, dict)
        }
        refs: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for signal in signals:
            refs.append(signal.source.to_dict())
            items.append(
                {
                    "source_id": signal.source.source_id,
                    "source_item_id": signal.source.external_id or signal.signal_id,
                    "title": signal.title,
                    "summary": signal.summary or signal.content or signal.title,
                    "url": signal.url,
                    "entities": entities_by_signal.get(signal.signal_id, []),
                }
            )
        return BoardEvidenceBundle(refs=refs, items=items)


__all__ = ["BoardEvidenceAssemblyService", "BoardEvidenceBundle"]
