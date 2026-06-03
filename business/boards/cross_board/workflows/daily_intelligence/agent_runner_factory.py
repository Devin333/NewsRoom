from __future__ import annotations

from framework.llm import LLMClient
from infrastructure.storage.conversation import LocalJsonConversationStore

from business.boards.cross_board.workflows.daily_intelligence.agent_loop_integration import (
    DailyAgentInputCanonicalizingRunner,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_fixtures import (
    DAILY_AGENT_FIXTURE_SCENARIO_PASS,
    build_daily_agent_fake_llm_client,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_registry import (
    build_daily_agent_runner,
)
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE_OFFLINE,
)


def build_profiled_daily_agent_runner(
    *,
    profile: str,
    llm_client: LLMClient | None = None,
    conversation_store: LocalJsonConversationStore | None = None,
    topic: str | None = None,
    fixture_scenario: str | None = None,
) -> DailyAgentInputCanonicalizingRunner:
    resolved_llm_client = llm_client
    if resolved_llm_client is None and profile in {PROFILE_AGENTIC_OFFLINE, PROFILE_LIVE_OFFLINE}:
        resolved_llm_client = build_daily_agent_fake_llm_client(
            profile,
            topic=topic,
            scenario=fixture_scenario or DAILY_AGENT_FIXTURE_SCENARIO_PASS,
        )
    return build_daily_agent_runner(
        profile=profile,
        llm_client=resolved_llm_client,
        conversation_store=conversation_store,
        topic=topic,
    )


__all__ = ["build_profiled_daily_agent_runner"]
