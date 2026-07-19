from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import GateResult, QualityFlag, require_text


class ResearchQualityResult(PrimitiveModel):
    result_id: str
    target_id: str
    target_type: Literal[
        "paper_card",
        "taxonomy",
        "summary",
        "reader_payload",
        "reading_note",
        "code_repository",
        "benchmark",
        "method_graph",
        "agent_intelligence",
        "rag_context",
        "reader_repair",
    ]
    passed: bool
    score: float = 0.0
    gate_results: list[GateResult] = Field(default_factory=list)
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("result_id", "target_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "quality result fields")

    @field_validator("score")
    @classmethod
    def _bounded_score(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("quality score must be between 0 and 1")
        return numeric

    @model_validator(mode="after")
    def _derive_flags(self) -> "ResearchQualityResult":
        flags: list[QualityFlag] = []
        candidates = list(self.quality_flags)
        for result in self.gate_results:
            if not result.passed:
                candidates.extend(result.quality_flags)
        for flag in candidates:
            if flag not in flags:
                flags.append(flag)
        object.__setattr__(self, "quality_flags", flags)
        return self


__all__ = ["ResearchQualityResult"]
