from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedEvidenceCheckInput


class ProductizedQualityService:
    def evidence_check_input(
        self,
        *,
        board_run_result: Any,
        evidence_items: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
    ) -> ProductizedEvidenceCheckInput:
        source_ids = [ref.get("source_id") for ref in evidence_refs if isinstance(ref, dict)]
        claims = [
            {
                "claim_id": f"claim-{index}",
                "text": card.summary,
                "citation_source_ids": source_ids,
            }
            for index, card in enumerate(board_run_result.cards)
        ] or [{"claim_id": "empty", "text": "No cards"}]
        sources = [
            {
                "source_id": str(item.get("source_id") or index),
                "text": str(item.get("summary") or item.get("title") or ""),
                "url": str(item.get("url") or ""),
            }
            for index, item in enumerate(evidence_items)
        ] or [{"source_id": "empty", "text": "No sources"}]
        return ProductizedEvidenceCheckInput(claims=claims, sources=sources)

    def merge_quality_summary(
        self,
        *,
        board_run_result: Any,
        evidence_checking: dict[str, Any],
        skill_traces: list[dict[str, Any]],
    ) -> dict[str, Any]:
        quality = (
            board_run_result.quality_summary.to_dict()
            if board_run_result.quality_summary is not None
            else {"status": "unchecked", "score": None}
        )
        quality["evidence_checking"] = evidence_checking
        quality["skill_trace_metadata"] = skill_traces
        return quality


__all__ = ["ProductizedQualityService"]
