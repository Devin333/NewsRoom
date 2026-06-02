from __future__ import annotations

from framework.agent.session import AgentSessionItem

from business.boards.paper_radar.agents.comparison_agent import PaperComparisonAgent
from business.boards.paper_radar.agents.evidence_verification_agent import PaperEvidenceVerificationAgent
from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAnalysisRequest
from business.boards.paper_radar.agents.quality_agent import PaperQualityAgent
from business.boards.paper_radar.agents.reader_agent_adapter import PaperReaderAgentAdapter
from business.boards.paper_radar.agents.reproducibility_agent import PaperReproducibilityAgent
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_BENCHMARK_CLAIMS,
    PAPER_ROLE_COMPARISON_RESULT,
    PAPER_ROLE_EVIDENCE_VERIFICATION,
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_READER_ANSWER,
    PAPER_ROLE_REPRODUCIBILITY_RESULT,
    PAPER_ROLE_SEMANTIC_SECTIONS,
    PAPER_ROLE_TAXONOMY_RESULT,
)


def test_evidence_verification_reads_benchmark_claims_role() -> None:
    request = PaperAnalysisRequest(paper_id="paper-1", run_id="run-1", title="Paper", abstract="Abstract")
    experiment = _item(
        request,
        role=PAPER_ROLE_EXPERIMENT_RESULT,
        content={"benchmarks": [{"claimId": "from-experiment", "value": 1, "evidence": "Experiment evidence."}]},
    )
    benchmark_claims = _item(
        request,
        role=PAPER_ROLE_BENCHMARK_CLAIMS,
        content={"claims": [{"claimId": "from-claims-role", "value": 2, "evidence": "Claims evidence."}]},
    )

    result = PaperEvidenceVerificationAgent().run(PaperAgentContext(request=request, shared_items=(experiment, benchmark_claims)))

    assert result.role == PAPER_ROLE_EVIDENCE_VERIFICATION
    assert [item["claimId"] for item in result.output["verifiedClaims"]] == ["from-claims-role"]


def test_quality_agent_degrades_score_from_weak_verification() -> None:
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
    taxonomy = _item(request, role=PAPER_ROLE_TAXONOMY_RESULT, content={"evidenceSummary": "SWE-bench evidence."})
    experiment = _item(
        request,
        role=PAPER_ROLE_EXPERIMENT_RESULT,
        content={"benchmarks": [{"name": "SWE-bench", "metric": "resolved", "value": 32.4, "baseline": "GPT-4", "evidence": "Table 2."}]},
    )
    verification = _item(
        request,
        role=PAPER_ROLE_EVIDENCE_VERIFICATION,
        content={
            "weakClaims": [
                {"claimId": "bench-swe-bench"},
                {"claimId": "bench-humaneval"},
                {"claimId": "bench-mbpp"},
                {"claimId": "bench-mmlu"},
            ],
            "rejectedClaims": [],
            "verifiedClaims": [],
        },
    )

    result = PaperQualityAgent().run(PaperAgentContext(request=request, shared_items=(taxonomy, experiment, verification)))

    assert result.role == PAPER_ROLE_QUALITY_RESULT
    assert result.output["qualityScore"] < 1.0
    assert "unverified_benchmark_claim" in result.output["riskFlags"]
    assert any("weak or rejected" in item for item in result.output["weaknesses"])


def test_reproducibility_agent_warns_when_repo_unavailable() -> None:
    request = PaperAnalysisRequest(paper_id="paper-1", run_id="run-1", title="Paper", abstract="Abstract")

    result = PaperReproducibilityAgent().run(PaperAgentContext(request=request, shared_items=()))

    assert result.role == PAPER_ROLE_REPRODUCIBILITY_RESULT
    assert result.output["hasCode"] is False
    assert result.warnings == ("repo_unavailable",)


def test_comparison_agent_warns_when_memory_unavailable() -> None:
    request = PaperAnalysisRequest(paper_id="paper-1", run_id="run-1", title="Paper", abstract="Abstract")
    taxonomy = _item(request, role=PAPER_ROLE_TAXONOMY_RESULT, content={"primaryTaskGroup": "code-ai", "methodRefs": []})

    result = PaperComparisonAgent().run(PaperAgentContext(request=request, shared_items=(taxonomy,)))

    assert result.role == PAPER_ROLE_COMPARISON_RESULT
    assert result.warnings == ("memory_unavailable",)
    assert result.output["warnings"] == ["memory_unavailable"]


def test_reader_agent_adapter_answers_from_final_profile_and_session_evidence() -> None:
    request = PaperAnalysisRequest(paper_id="paper-1", run_id="run-1", title="Paper", abstract="Abstract")
    final_profile = _item(
        request,
        role=PAPER_ROLE_FINAL_PROFILE,
        content={"evidenceSummary": "The paper reports a SWE-bench result."},
    )
    experiment = _item(
        request,
        role=PAPER_ROLE_EXPERIMENT_RESULT,
        content={"benchmarks": [{"claimId": "bench-swe", "evidence": "SWE-bench reports 32.4% resolved."}]},
    )
    sections = _item(
        request,
        role=PAPER_ROLE_SEMANTIC_SECTIONS,
        content={"sections": [{"sectionId": "exp-1", "title": "Experiments"}]},
    )

    result = PaperReaderAgentAdapter().run(PaperAgentContext(request=request, shared_items=(final_profile, experiment, sections)))

    assert result.role == PAPER_ROLE_READER_ANSWER
    assert result.output["answer"] == "The paper reports a SWE-bench result."
    assert result.output["citations"]
    assert result.output["evidence"] == result.output["citations"]


def _item(request: PaperAnalysisRequest, *, role: str, content: dict[str, object]) -> AgentSessionItem:
    return AgentSessionItem(
        session_id=request.session_id,
        run_id=request.run_id,
        agent_id=f"{role}-agent",
        role=role,
        content=content,
    )
