from __future__ import annotations

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAnalysisRequest
from business.boards.paper_radar.agents.quality_agent import PaperQualityAgent
from business.boards.paper_radar.agents.roles import PAPER_ROLE_EXPERIMENT_RESULT, PAPER_ROLE_QUALITY_RESULT, PAPER_ROLE_TAXONOMY_RESULT


def test_quality_agent_scores_experiment_result() -> None:
    request = PaperAnalysisRequest(
        paper_id="paper-1",
        run_id="run-1",
        title="SWE-bench Agent",
        abstract="The system improves software engineering results.",
        repo_url="https://github.com/example/repo",
        page_sections=(
            {"title": "Experiments", "sectionType": "experiment", "textExcerpt": "Evaluation results."},
            {"title": "Limitations", "sectionType": "limitation", "textExcerpt": "Limitations are discussed."},
        ),
    )
    taxonomy_item = AgentSessionItem(
        session_id=request.session_id,
        agent_id="paper-taxonomy-agent",
        role=PAPER_ROLE_TAXONOMY_RESULT,
        content={"evidenceSummary": "SWE-bench evidence."},
    )
    experiment_item = AgentSessionItem(
        session_id=request.session_id,
        agent_id="paper-experiment-agent",
        role=PAPER_ROLE_EXPERIMENT_RESULT,
        content={
            "benchmarks": [
                {"name": "SWE-bench", "metric": "resolved", "value": 32.4, "baseline": "GPT-4", "evidence": "Table 2."}
            ]
        },
    )

    result = PaperQualityAgent().run(PaperAgentContext(request=request, shared_items=(taxonomy_item, experiment_item)))

    assert result.role == PAPER_ROLE_QUALITY_RESULT
    assert result.output["qualityScore"] >= 0.9
    assert result.output["evidenceStrength"] == "high"
    assert result.output["recommendation"] == "publish"
