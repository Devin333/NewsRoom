from __future__ import annotations

from backend.research.domain.common import GateResult, stable_research_id
from backend.research.domain.quality import ResearchQualityResult


class ResearchQualityGate:
    def evaluate(self, *, target_id: str, target_type: str, gate_results: list[GateResult]) -> ResearchQualityResult:
        passed = all(result.passed for result in gate_results)
        score = 1.0 if passed else max(0.0, 1.0 - (sum(not result.passed for result in gate_results) / max(len(gate_results), 1)))
        return ResearchQualityResult(
            result_id=stable_research_id("quality", target_type, target_id),
            target_id=target_id,
            target_type=target_type,
            passed=passed,
            score=score,
            gate_results=gate_results,
        )


__all__ = ["ResearchQualityGate"]
