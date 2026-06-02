from __future__ import annotations

from typing import Any

from business.boards.domain import BoardEvidenceAssemblyService, BoardEvidenceBundle
from business.boards.productized.models import ProductizedRunState
from business.foundation import Signal


class ProductizedEvidenceService:
    def __init__(self, *, evidence_service: BoardEvidenceAssemblyService | None = None) -> None:
        self.evidence_service = evidence_service or BoardEvidenceAssemblyService()

    def build(
        self,
        signals: list[Signal],
        *,
        extracted_entities: list[dict[str, Any]],
    ) -> BoardEvidenceBundle:
        return self.evidence_service.build(signals, extracted_entities=extracted_entities)

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
