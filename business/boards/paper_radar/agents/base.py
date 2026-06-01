"""Protocol implemented by paper radar analysis sub-agents."""

from __future__ import annotations

from typing import Protocol

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult


class PaperAgent(Protocol):
    """Synchronous interface for a deterministic paper analysis agent."""

    agent_id: str

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        """Analyze the provided context and return a structured result."""
        ...
