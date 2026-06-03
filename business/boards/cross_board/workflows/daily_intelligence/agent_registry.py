from __future__ import annotations

from typing import Any, cast

from framework.agent import AgentRunner, AgentSpec
from framework.llm import (
    LLMClient,
    build_openai_compatible_client_from_config,
)
from infrastructure.storage.conversation import LocalJsonConversationStore
from business.boards.cross_board.workflows.daily_intelligence.agent_loop_integration import (
    DailyAgentInputCanonicalizingRunner,
    build_daily_output_judge,
    normalize_daily_agent_output,
)
from business.boards.cross_board.workflows.daily_intelligence.agent_tools import build_daily_agent_tool_registry
from business.boards.cross_board.workflows.daily_intelligence.agents import (
    ANALYST_AGENT_ID,
    EDITOR_AGENT_ID,
    PLANNER_AGENT_ID,
    VERIFIER_AGENT_ID,
    WRITER_AGENT_ID,
    build_analyst_agent,
    build_editor_agent,
    build_planner_agent,
    build_verifier_agent,
    build_writer_agent,
)
from business.boards.cross_board.workflows.daily_intelligence.profiles import (
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE_OFFLINE,
)


DAILY_AGENTIC_MODEL_ROUTE_ID = "daily-intelligence-agentic"


def build_daily_agent_registry() -> dict[str, AgentSpec]:
    return {
        PLANNER_AGENT_ID: build_planner_agent(),
        ANALYST_AGENT_ID: build_analyst_agent(),
        WRITER_AGENT_ID: build_writer_agent(),
        VERIFIER_AGENT_ID: build_verifier_agent(),
        EDITOR_AGENT_ID: build_editor_agent(),
    }


def build_daily_agent_runner(
    *,
    profile: str,
    llm_client: LLMClient | None = None,
    conversation_store: LocalJsonConversationStore | None = None,
    topic: str | None = None,
) -> DailyAgentInputCanonicalizingRunner:
    _ = topic
    if llm_client is None and profile in {PROFILE_AGENTIC_OFFLINE, PROFILE_LIVE_OFFLINE}:
        raise ValueError(
            "offline daily agent runner requires an explicit llm_client; "
            "use build_profiled_daily_agent_runner for fixture-backed offline runs"
        )
    resolved_llm_client = llm_client or build_openai_compatible_client_from_config(
        route_id=DAILY_AGENTIC_MODEL_ROUTE_ID
    )
    runner = AgentRunner(
        llm_client=cast(Any, resolved_llm_client),
        tool_registry=build_daily_agent_tool_registry(),
        conversation_store=conversation_store,
        output_judge=build_daily_output_judge(),
        output_normalizer=normalize_daily_agent_output,
    )
    return DailyAgentInputCanonicalizingRunner(runner)

