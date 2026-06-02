from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedEvidenceCheckInput, ProductizedRunState
from business.foundation.skills import BusinessSkillRuntime


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


class ProductizedQualitySummaryService:
    def __init__(
        self,
        *,
        skill_runtime: BusinessSkillRuntime,
        quality_service: ProductizedQualityService | None = None,
    ) -> None:
        self.skill_runtime = skill_runtime
        self.quality_service = quality_service or ProductizedQualityService()

    def build_summary(
        self,
        *,
        request: dict[str, Any],
        board_run_result: Any,
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        evidence_input = self.quality_service.evidence_check_input(
            board_run_result=board_run_result,
            evidence_items=productized_run.evidence_items,
            evidence_refs=productized_run.evidence_refs,
        )
        evidence_check = self.skill_runtime.run_evidence_checking(
            evidence_input.claims,
            evidence_input.sources,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(evidence_check.to_dict())
        quality = self.quality_service.merge_quality_summary(
            board_run_result=board_run_result,
            evidence_checking=evidence_check.output,
            skill_traces=skill_traces,
        )
        run_state = productized_run.with_updates(skill_traces=skill_traces)
        return {
            "quality_summary": quality,
            "evidence_checking": evidence_check.output,
            "skill_traces": skill_traces,
            "productized_run": run_state,
        }


__all__ = ["ProductizedQualityService", "ProductizedQualitySummaryService"]
