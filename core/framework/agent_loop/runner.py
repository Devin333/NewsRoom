from __future__ import annotations

from typing import Any

from core.framework.agent_loop.loop import AgentLoop
from core.framework.agent_loop.models import AgentLoopResult, AgentSpec
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.agent_loop.judge import OutputJudge
from core.framework.llm import LLMClient
from core.framework.tools import ToolExecutor, ToolRegistry


class AgentRunner:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
    ) -> None:
        self._llm_client = llm_client
        self._tool_registry = tool_registry

    def run(self, agent: AgentSpec, inputs: dict[str, Any]) -> AgentLoopResult:
        tools = self._tool_registry.export_schema_for_llm(agent.allowed_tools)
        loop = AgentLoop(
            llm_client=self._llm_client,
            tool_executor=ToolExecutor(self._tool_registry),
            prompt_builder=PromptBuilder(),
            action_parser=AgentActionParser(),
            output_judge=OutputJudge(),
        )
        return loop.run(agent, inputs, tools)
