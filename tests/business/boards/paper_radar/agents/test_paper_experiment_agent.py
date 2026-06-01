from __future__ import annotations

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.experiment_agent import PaperExperimentAgent
from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAnalysisRequest
from business.boards.paper_radar.agents.roles import PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_TAXONOMY_RESULT


def test_experiment_agent_extracts_benchmark_candidate() -> None:
    request = PaperAnalysisRequest(
        paper_id="paper-1",
        run_id="run-1",
        title="SWE-bench Agent",
        abstract="On SWE-bench, our agent achieves 32.4% resolved compared with GPT-4.",
        page_sections=(
            {
                "title": "Experiments",
                "sectionType": "experiment",
                "textExcerpt": "Evaluation on SWE-bench reports 32.4% resolved compared with GPT-4.",
            },
        ),
    )
    taxonomy_item = AgentSessionItem(
        session_id=request.session_id,
        agent_id="paper-taxonomy-agent",
        role=PAPER_ROLE_TAXONOMY_RESULT,
        content={"primaryTaskGroup": "code-ai", "benchmarkCategories": ["software-engineering"]},
    )

    result = PaperExperimentAgent().run(PaperAgentContext(request=request, shared_items=(taxonomy_item,)))

    assert result.role == PAPER_ROLE_EXPERIMENT_RESULT
    assert result.output["benchmarks"][0]["name"] == "SWE-bench"
    assert result.output["benchmarks"][0]["metric"] == "resolved"
    assert result.output["benchmarks"][0]["value"] == 32.4
    assert result.output["benchmarks"][0]["baseline"] == "GPT-4"
