"""Memory write agent for final paper analysis outputs."""

from __future__ import annotations

from framework.agent.session import AgentSessionItem
from framework.memory.session import AgentSessionMemoryAdapter

from business.boards.paper_radar.agents.models import PaperAgentContext, PaperAgentResult
from business.boards.paper_radar.agents.roles import PAPER_ROLE_FINAL_PROFILE, PAPER_ROLE_MEMORY_RECORDS
from business.boards.paper_radar.agents.utils.evidence import latest_output


class PaperMemoryAgent:
    """Persist final profile summaries into long-term memory."""

    agent_id = "paper-memory-agent"
    required_roles = (PAPER_ROLE_FINAL_PROFILE,)
    produced_role = PAPER_ROLE_MEMORY_RECORDS

    def __init__(self, memory_adapter: AgentSessionMemoryAdapter | None = None) -> None:
        self._memory_adapter = memory_adapter or AgentSessionMemoryAdapter()

    def run(self, context: PaperAgentContext) -> PaperAgentResult:
        final_profile = latest_output(context.shared_items, PAPER_ROLE_FINAL_PROFILE)
        item = AgentSessionItem(
            session_id=context.request.session_id,
            run_id=context.request.run_id,
            agent_id=self.agent_id,
            role=PAPER_ROLE_FINAL_PROFILE,
            content=final_profile,
            summary=str(final_profile.get("evidenceSummary") or context.request.title),
            refs={"paperId": context.request.paper_id},
            status="final",
        )
        write_result = self._memory_adapter.write_item(item)
        warnings = tuple(write_result.get("warnings") or ())
        output = {
            "memoryRecords": [
                {
                    "kind": "semantic",
                    "scope": "paper",
                    "summary": item.summary,
                    "content": {},
                    "refs": {"paperId": context.request.paper_id},
                }
            ],
            "writeResult": write_result,
        }
        return PaperAgentResult(
            agent_id=self.agent_id,
            role=self.produced_role,
            output=output,
            summary="Final profile memory write attempted.",
            confidence=0.8 if self._memory_adapter.available else 0.45,
            warnings=warnings,
        )
