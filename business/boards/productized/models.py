from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import BoardType, PrimitiveModel


class ProductizedRunState(PrimitiveModel):
    schema_version: str = "business.board.productized.run_state.v1"
    board_type: BoardType
    run_id: str
    topic: str | None = None
    fail_on_skill_error: bool = False
    skill_traces: list[dict[str, Any]] = Field(default_factory=list)
    source_reliability_results: list[dict[str, Any]] = Field(default_factory=list)
    extracted_entities: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    deduplication_result: dict[str, Any] = Field(default_factory=dict)
    trend_analysis: dict[str, Any] = Field(default_factory=dict)
    improvement_context: dict[str, Any] = Field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "ProductizedRunState":
        return self.model_copy(update=updates)

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "skill_trace_metadata": list(self.skill_traces),
            "extracted_entities": list(self.extracted_entities),
            "evidence_items": list(self.evidence_items),
            "trend_analysis": dict(self.trend_analysis),
            "deduplication_result": dict(self.deduplication_result),
            "improvement_context": dict(self.improvement_context),
            "productized_run_state": self.to_dict(),
        }

    @classmethod
    def from_request(cls, *, request: dict[str, Any], board_type: BoardType, run_id: str) -> "ProductizedRunState":
        return cls(
            board_type=board_type,
            run_id=run_id,
            topic=request.get("topic"),
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )


class ProductizedEvidenceBundle(PrimitiveModel):
    refs: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


class ProductizedEvidenceCheckInput(PrimitiveModel):
    claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


__all__ = ["ProductizedEvidenceBundle", "ProductizedEvidenceCheckInput", "ProductizedRunState"]
