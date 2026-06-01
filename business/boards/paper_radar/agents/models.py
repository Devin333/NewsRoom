"""Data models for paper radar multi-agent analysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from framework.agent.session import AgentSessionItem


@dataclass(frozen=True)
class PaperAnalysisRequest:
    """Input data for one paper analysis run."""

    paper_id: str
    run_id: str
    title: str
    abstract: str
    full_text: str | None = None
    page_sections: tuple[Mapping[str, Any], ...] = ()
    repo_url: str | None = None
    github_stars: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        """Return the stable shared session id for this paper run."""

        return f"paper-analysis:{self.paper_id}:{self.run_id}"


@dataclass(frozen=True)
class PaperAgentContext:
    """Context passed to a paper sub-agent by the orchestrator."""

    request: PaperAnalysisRequest
    shared_items: tuple[AgentSessionItem, ...]


@dataclass(frozen=True)
class PaperAgentResult:
    """Structured result returned by one paper sub-agent."""

    agent_id: str
    role: str
    output: Mapping[str, Any]
    summary: str | None = None
    confidence: float | None = None
    evidence_refs: tuple[Mapping[str, Any], ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaperAnalysisResult:
    """Final result returned by the paper analysis orchestrator."""

    paper_id: str
    run_id: str
    session_id: str
    final_profile: Mapping[str, Any]
    agent_outputs: Mapping[str, Any]
    low_confidence_items: tuple[Mapping[str, Any], ...] = ()
    errors: tuple[str, ...] = ()
