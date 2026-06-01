from __future__ import annotations

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAnalysisRequest
from business.boards.paper_radar.agents.roles import PAPER_ROLE_TAXONOMY_RESULT
from business.boards.paper_radar.agents.taxonomy_agent import PaperTaxonomyAgent


def test_taxonomy_agent_outputs_taxonomy_result() -> None:
    request = PaperAnalysisRequest(
        paper_id="paper-1",
        run_id="run-1",
        title="Agentic Language Models for SWE-bench",
        abstract="We use transformer language models as agents for software engineering tasks on SWE-bench.",
    )

    result = PaperTaxonomyAgent().run(PaperAgentContext(request=request, shared_items=()))

    assert result.role == PAPER_ROLE_TAXONOMY_RESULT
    assert result.output["primaryTaskGroup"] in {"agents", "language-models", "code-ai"}
    assert result.output["taskRefs"]
    assert result.output["methodRefs"]
    assert "software-engineering" in result.output["benchmarkCategories"]
    assert result.confidence is not None and result.confidence > 0.5
