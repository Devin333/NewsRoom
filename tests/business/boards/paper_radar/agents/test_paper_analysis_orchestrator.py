from __future__ import annotations

import json
from collections.abc import Sequence

from framework.agent.session import AgentSharedWorkspace, AgentSessionItem, InMemoryAgentSessionStore

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult, PaperAnalysisRequest
from business.boards.paper_radar.agents.orchestrator import PaperAnalysisOrchestrator
from business.boards.paper_radar.agents.roles import (
    PAPER_ROLE_EXPERIMENT_RESULT,
    PAPER_ROLE_FINAL_PROFILE,
    PAPER_ROLE_METADATA,
    PAPER_ROLE_QUALITY_RESULT,
    PAPER_ROLE_TAXONOMY_RESULT,
)


def test_orchestrator_writes_metadata_taxonomy_experiment_quality_and_final_profile() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    request = _request()

    result = PaperAnalysisOrchestrator(workspace=workspace).analyze_paper(request)

    roles = [item.role for item in workspace.read(session_id=request.session_id)]
    assert roles == [
        PAPER_ROLE_METADATA,
        PAPER_ROLE_TAXONOMY_RESULT,
        PAPER_ROLE_EXPERIMENT_RESULT,
        PAPER_ROLE_QUALITY_RESULT,
        PAPER_ROLE_FINAL_PROFILE,
    ]
    assert result.final_profile["taskRefs"]
    assert result.final_profile["methodRefs"]
    assert result.final_profile["classification"]["agentSessionId"] == request.session_id


def test_orchestrator_degrades_when_agent_fails() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    request = _request()

    result = PaperAnalysisOrchestrator(workspace=workspace, taxonomy_agent=FailingAgent()).analyze_paper(request)

    assert result.errors
    assert result.final_profile["lowConfidenceItems"]
    assert workspace.latest(session_id=request.session_id, role=PAPER_ROLE_FINAL_PROFILE) is not None


def test_raw_full_text_is_not_written_to_workspace() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    request = PaperAnalysisRequest(
        paper_id="paper-1",
        run_id="run-1",
        title="Agentic Language Models",
        abstract="A transformer language model agent is evaluated on SWE-bench with 32.4% resolved.",
        full_text="SECRET FULL TEXT SHOULD NOT BE WRITTEN",
        metadata={"raw_payload": {"full_text": "hidden"}},
    )

    PaperAnalysisOrchestrator(workspace=workspace).analyze_paper(request)

    payload = json.dumps([item.content for item in workspace.read(session_id=request.session_id)], sort_keys=True)
    assert "SECRET FULL TEXT" not in payload
    assert "full_text" not in payload
    assert "raw_payload" not in payload


def test_different_paper_sessions_do_not_share_items() -> None:
    workspace = AgentSharedWorkspace(InMemoryAgentSessionStore())
    orchestrator = PaperAnalysisOrchestrator(workspace=workspace)
    first = _request(paper_id="paper-1", run_id="run-1")
    second = _request(paper_id="paper-2", run_id="run-1")

    orchestrator.analyze_paper(first)
    orchestrator.analyze_paper(second)

    assert all(item.session_id == first.session_id for item in workspace.read(session_id=first.session_id))
    assert all(item.session_id == second.session_id for item in workspace.read(session_id=second.session_id))


def _request(paper_id: str = "paper-1", run_id: str = "run-1") -> PaperAnalysisRequest:
    return PaperAnalysisRequest(
        paper_id=paper_id,
        run_id=run_id,
        title="Agentic Language Models for SWE-bench",
        abstract="A transformer language model agent achieves 32.4% resolved on SWE-bench compared with GPT-4.",
        repo_url="https://github.com/example/repo",
        github_stars=100,
        page_sections=(
            {"title": "Experiments", "sectionType": "experiment", "textExcerpt": "SWE-bench reports 32.4% resolved compared with GPT-4."},
            {"title": "Limitations", "sectionType": "limitation", "textExcerpt": "Limitations are discussed."},
        ),
    )


class FailingAgent:
    agent_id = "failing-agent"

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        raise RuntimeError("agent failed")
