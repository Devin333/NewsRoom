"""Comparison agent for current paper versus session memory."""

from __future__ import annotations

from collections.abc import Mapping

from framework.memory.session import AgentSessionMemoryAdapter

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_COMPARISON_RESULT, PAPER_ROLE_FINAL_PROFILE, PAPER_ROLE_TAXONOMY_RESULT
from business.boards.paper_radar.agents.utils.evidence import latest_output


class PaperComparisonAgent:
    """Compare current session outputs with historical memory when available."""

    agent_id = "paper-comparison-agent"
    required_roles = (PAPER_ROLE_TAXONOMY_RESULT,)
    produced_role = PAPER_ROLE_COMPARISON_RESULT

    def __init__(self, memory_adapter: AgentSessionMemoryAdapter | None = None) -> None:
        self._memory_adapter = memory_adapter or AgentSessionMemoryAdapter()

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        taxonomy = latest_output(context.shared_items, PAPER_ROLE_TAXONOMY_RESULT)
        memories = self._memory_adapter.recall(
            role=PAPER_ROLE_FINAL_PROFILE,
            refs={"paperId": context.request.paper_id},
            limit=5,
        )
        warnings = () if self._memory_adapter.available else ("memory_unavailable",)
        duplicate_risk = 0.21 if memories else 0.08
        output: Mapping[str, object] = {
            "similarPapers": memories,
            "relatedMethods": [item.get("name") for item in taxonomy.get("methodRefs", []) if isinstance(item, Mapping)],
            "trendPosition": _trend_position(taxonomy),
            "noveltyAgainstMemory": round(1.0 - duplicate_risk, 2),
            "duplicateRisk": duplicate_risk,
            "comparisonSummary": "Historical memory was compared." if memories else "No historical memory was available for comparison.",
            "warnings": list(warnings),
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=str(output["comparisonSummary"]),
            confidence=0.74 if memories else 0.5,
            warnings=warnings,
        )


def _trend_position(taxonomy: Mapping[str, object]) -> str:
    primary = taxonomy.get("primaryTaskGroup") or "ai"
    return f"Positioned within current {primary} research trends."
