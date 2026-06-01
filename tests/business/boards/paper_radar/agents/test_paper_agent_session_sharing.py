from __future__ import annotations

from framework.agent.session import AgentSharedWorkspace, InMemoryAgentSessionStore

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult, PaperAnalysisRequest
from business.boards.paper_radar.agents.orchestrator import PaperAnalysisOrchestrator
from business.boards.paper_radar.agents.roles import PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_METADATA, PAPER_ROLE_QUALITY_RESULT, PAPER_ROLE_TAXONOMY_RESULT


def test_experiment_and_quality_agents_receive_prior_results_from_shared_workspace() -> None:
    experiment = CapturingExperimentAgent()
    quality = CapturingQualityAgent()
    request = PaperAnalysisRequest(
        paper_id="paper-1",
        run_id="run-1",
        title="Paper",
        abstract="Abstract",
    )

    PaperAnalysisOrchestrator(
        workspace=AgentSharedWorkspace(InMemoryAgentSessionStore()),
        taxonomy_agent=StaticTaxonomyAgent(),
        experiment_agent=experiment,
        quality_agent=quality,
    ).analyze_paper(request)

    assert experiment.received_roles == (PAPER_ROLE_METADATA, PAPER_ROLE_TAXONOMY_RESULT)
    assert quality.received_roles == (PAPER_ROLE_TAXONOMY_RESULT, PAPER_ROLE_EXPERIMENT_RESULT)


class StaticTaxonomyAgent:
    agent_id = "static-taxonomy-agent"

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_TAXONOMY_RESULT,
            output={
                "primaryTaskGroup": "code-ai",
                "taskRefs": [{"id": "task-code-ai", "slug": "code-ai", "name": "Code AI"}],
                "methodRefs": [{"id": "method-language-models", "slug": "language-models", "name": "Language Models"}],
                "confidence": 0.8,
                "evidenceSummary": "Static taxonomy.",
            },
            confidence=0.8,
        )


class CapturingExperimentAgent:
    agent_id = "capturing-experiment-agent"

    def __init__(self) -> None:
        self.received_roles: tuple[str, ...] = ()

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        self.received_roles = tuple(item.role for item in context.shared_items)
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_EXPERIMENT_RESULT,
            output={"benchmarks": [], "experimentSummary": "No benchmark.", "metricWarnings": []},
            confidence=0.7,
        )


class CapturingQualityAgent:
    agent_id = "capturing-quality-agent"

    def __init__(self) -> None:
        self.received_roles: tuple[str, ...] = ()

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        self.received_roles = tuple(item.role for item in context.shared_items)
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=PAPER_ROLE_QUALITY_RESULT,
            output={"qualityScore": 0.6, "evidenceStrength": "medium", "weaknesses": [], "recommendation": "manual_review"},
            confidence=0.6,
        )
