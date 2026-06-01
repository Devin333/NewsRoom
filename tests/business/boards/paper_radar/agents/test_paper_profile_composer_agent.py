from __future__ import annotations

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAnalysisRequest
from business.boards.paper_radar.agents.profile_composer_agent import PaperProfileComposerAgent
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_TAXONOMY_RESULT,
)


def test_profile_composer_outputs_public_paper_compatible_profile() -> None:
    request = PaperAnalysisRequest(paper_id="paper-1", run_id="run-1", title="Paper", abstract="Abstract")
    items = (
        AgentSessionItem(
            session_id=request.session_id,
            agent_id="paper-taxonomy-agent",
            role=PAPER_ROLE_TAXONOMY_RESULT,
            content={
                "primaryTaskGroup": "code-ai",
                "secondaryTaskGroups": ["agents"],
                "taskRefs": [{"id": "task-code-ai", "slug": "code-ai", "name": "Code AI", "group": "code-ai"}],
                "methodRefs": [{"id": "method-language-models", "slug": "language-models", "name": "Language Models"}],
                "confidence": 0.8,
                "evidenceSummary": "Taxonomy evidence.",
            },
            confidence=0.8,
        ),
        AgentSessionItem(
            session_id=request.session_id,
            agent_id="paper-experiment-agent",
            role=PAPER_ROLE_EXPERIMENT_RESULT,
            content={"benchmarks": [{"id": "bench-swe-bench", "name": "SWE-bench", "metric": "resolved", "value": 32.4}]},
            confidence=0.8,
        ),
        AgentSessionItem(
            session_id=request.session_id,
            agent_id="paper-quality-agent",
            role=PAPER_ROLE_QUALITY_RESULT,
            content={"qualityScore": 0.78, "evidenceStrength": "high", "weaknesses": [], "recommendation": "publish"},
            confidence=0.78,
        ),
    )

    result = PaperProfileComposerAgent().run(PaperAgentContext(request=request, shared_items=items))

    assert result.role == PAPER_ROLE_FINAL_PROFILE
    assert result.output["taskRefs"][0]["slug"] == "code-ai"
    assert result.output["methodRefs"][0]["slug"] == "language-models"
    assert result.output["benchmarks"][0]["name"] == "SWE-bench"
    assert result.output["classification"]["agentSessionId"] == request.session_id
    assert "aiSummary" in result.output
