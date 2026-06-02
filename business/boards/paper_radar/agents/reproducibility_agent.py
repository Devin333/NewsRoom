"""Reproducibility analysis agent for paper repositories."""

from __future__ import annotations

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_REPRODUCIBILITY_RESULT


class PaperReproducibilityAgent:
    """Estimate reproducibility from safe repository metadata only."""

    agent_id = "paper-reproducibility-agent"
    required_roles = ()
    produced_role = PAPER_ROLE_REPRODUCIBILITY_RESULT

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        has_code = bool(context.request.repo_url)
        warnings = [] if has_code else ["repo_unavailable"]
        stars = int(context.request.github_stars or 0)
        score = 0.68 if has_code else 0.32
        if stars >= 100:
            score += 0.08
        output = {
            "reproducibilityScore": round(min(0.95, score), 2),
            "hasCode": has_code,
            "hasTrainingScript": None,
            "hasEvalScript": None,
            "hasPretrainedModel": None,
            "hasDatasetScript": None,
            "license": None,
            "repoHealth": "active" if stars >= 50 else "unknown" if has_code else "unavailable",
            "setupComplexity": "unknown",
            "warnings": warnings,
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary="Repository metadata is available." if has_code else "Repository metadata is unavailable.",
            confidence=float(output["reproducibilityScore"]),
            warnings=tuple(warnings),
        )
