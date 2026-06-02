from __future__ import annotations

from dataclasses import dataclass
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

    def board_output_metadata(self) -> dict[str, Any]:
        return {
            "skill_trace_metadata": list(self.skill_traces),
            "improvement_context": dict(self.improvement_context),
            "trend_analysis": dict(self.trend_analysis),
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


@dataclass(frozen=True)
class ProductizedBoardOutputBundle:
    board_run_result: Any
    board_output: dict[str, Any]
    cards: list[dict[str, Any]]
    detail_pages: list[dict[str, Any]]
    insights: list[dict[str, Any]]
    summary_md: str
    skill_traces: list[dict[str, Any]]
    run_state: ProductizedRunState

    def to_step_outputs(self) -> dict[str, Any]:
        return {
            "board_run_result": self.board_run_result,
            "board_output": self.board_output,
            "cards": self.cards,
            "detail_pages": self.detail_pages,
            "insights": self.insights,
            "summary_md": self.summary_md,
            "skill_traces": self.skill_traces,
            "productized_run": self.run_state,
        }


__all__ = [
    "ProductizedBoardOutputBundle",
    "ProductizedEvidenceBundle",
    "ProductizedEvidenceCheckInput",
    "ProductizedRunState",
]
