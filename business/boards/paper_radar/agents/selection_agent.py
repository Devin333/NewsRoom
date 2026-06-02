"""Paper selection agent for PaperRadar publication decisions."""

from __future__ import annotations

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_SELECTION_DECISION, PAPER_ROLE_SEMANTIC_SECTIONS


AI_TERMS = (
    "agent",
    "llm",
    "language model",
    "transformer",
    "benchmark",
    "machine learning",
    "neural",
    "reasoning",
    "multimodal",
    "retrieval",
    "code",
)


class PaperSelectionAgent:
    """Decide whether a paper should continue through PaperRadar analysis."""

    agent_id = "paper-selection-agent"
    required_roles = (PAPER_ROLE_SEMANTIC_SECTIONS,)
    produced_role = PAPER_ROLE_SELECTION_DECISION

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        text = f"{context.request.title}\n{context.request.abstract}".casefold()
        is_ai_related = any(term in text for term in AI_TERMS)
        has_pdf = bool(context.request.full_text or context.request.page_sections or context.request.pdf_artifact_uri)
        has_github = bool(context.request.repo_url)
        stars = int(context.request.github_stars or 0)
        topic_relevance = 0.86 if is_ai_related else 0.48
        engineering_value = 0.78 if has_github or stars > 0 or "benchmark" in text else 0.58
        if is_ai_related and has_pdf:
            decision = "publish"
        elif is_ai_related:
            decision = "manual_review"
        else:
            decision = "manual_review"
        output = {
            "decision": decision,
            "reason": "AI-related paper with analyzable text." if decision == "publish" else "Needs human confirmation before publication.",
            "confidence": min(0.95, topic_relevance),
            "signals": {
                "isAiRelated": is_ai_related,
                "hasPdf": has_pdf,
                "hasGithub": has_github,
                "githubStars": stars,
                "topicRelevance": topic_relevance,
                "engineeringValue": engineering_value,
                "duplicateRisk": 0.12,
            },
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary=str(output["reason"]),
            confidence=float(output["confidence"]),
        )
