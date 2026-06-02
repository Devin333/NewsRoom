"""Contribution analysis agent for paper radar."""

from __future__ import annotations

import re

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_CONTRIBUTION_RESULT, PAPER_ROLE_SEMANTIC_SECTIONS, PAPER_ROLE_TAXONOMY_RESULT


class PaperContributionAgent:
    """Extract contribution claims, novelty, and technical direction."""

    agent_id = "paper-contribution-agent"
    required_roles = (PAPER_ROLE_SEMANTIC_SECTIONS, PAPER_ROLE_TAXONOMY_RESULT)
    produced_role = PAPER_ROLE_CONTRIBUTION_RESULT

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        claims = _contribution_claims(context.request.title, context.request.abstract)
        novelty_score = 0.74 if any("new" in claim["claim"].casefold() or "novel" in claim["claim"].casefold() for claim in claims) else 0.62
        output = {
            "contributions": claims,
            "mainContributionSummary": claims[0]["claim"] if claims else context.request.title,
            "noveltyScore": novelty_score,
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=str(output["mainContributionSummary"]),
            confidence=novelty_score,
        )


def _contribution_claims(title: str, abstract: str) -> list[dict[str, object]]:
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", abstract) if item.strip()]
    candidates = [sentence for sentence in sentences if any(term in sentence.casefold() for term in ("propose", "introduce", "present", "contribute", "new", "novel"))]
    if not candidates:
        candidates = [abstract[:240] or title]
    return [
        {
            "claimId": f"contrib-{index:03d}",
            "type": _claim_type(sentence),
            "claim": sentence[:500],
            "novelty": "high" if "novel" in sentence.casefold() or "new" in sentence.casefold() else "medium",
            "evidence": sentence[:500],
            "confidence": 0.78,
        }
        for index, sentence in enumerate(candidates[:3], start=1)
    ]


def _claim_type(sentence: str) -> str:
    lowered = sentence.casefold()
    if "dataset" in lowered:
        return "dataset"
    if "benchmark" in lowered:
        return "benchmark"
    if "system" in lowered or "framework" in lowered:
        return "system"
    if "analysis" in lowered:
        return "analysis"
    return "method"
