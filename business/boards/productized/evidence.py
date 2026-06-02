from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedEvidenceBundle, ProductizedRunState
from business.foundation import Signal


class ProductizedEvidenceService:
    def build(
        self,
        signals: list[Signal],
        *,
        extracted_entities: list[dict[str, Any]],
    ) -> ProductizedEvidenceBundle:
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
        return ProductizedEvidenceBundle(refs=refs, items=items)

    def build_outputs(
        self,
        *,
        board_signals: list[Signal],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        bundle = self.build(
            board_signals,
            extracted_entities=productized_run.extracted_entities,
        )
        run_state = productized_run.with_updates(
            evidence_refs=bundle.refs,
            evidence_items=bundle.items,
        )
        return {
            "evidence_refs": bundle.refs,
            "evidence_items": bundle.items,
            "productized_run": run_state,
        }


__all__ = ["ProductizedEvidenceService"]
