from __future__ import annotations

from typing import Any

from core.framework.agent_loop.loop import AgentLoop
from core.framework.agent_loop.models import AgentLoopResult, AgentSpec
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.agent_loop.judge import OutputJudge
from core.framework.llm import LLMClient
from core.framework.tools import ToolExecutor, ToolRegistry
from storage.conversation import AgentMessageRecord, LocalJsonConversationStore


class AgentRunner:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        conversation_store: LocalJsonConversationStore | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._conversation_store = conversation_store

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        *,
        conversation_id: str | None = None,
    ) -> AgentLoopResult:
        self._append_conversation_message(
            conversation_id,
            AgentMessageRecord(
                conversation_id=conversation_id or "",
                role="user",
                content=inputs,
                agent_id=agent.agent_id,
                metadata={"message_type": "agent_inputs"},
            ),
        )
        tools = self._tool_registry.export_schema_for_llm(agent.allowed_tools)
        loop = AgentLoop(
            llm_client=self._llm_client,
            tool_executor=ToolExecutor(self._tool_registry),
            prompt_builder=PromptBuilder(),
            action_parser=AgentActionParser(),
            output_judge=OutputJudge(),
        )
        result = loop.run(agent, inputs, tools)
        self._append_conversation_message(
            conversation_id,
            AgentMessageRecord(
                conversation_id=conversation_id or "",
                role="assistant",
                content=_conversation_result_payload(result),
                agent_id=agent.agent_id,
                metadata={
                    "message_type": "agent_result",
                    "status": result.status.value,
                    "iterations": result.iterations,
                },
            ),
        )
        if self._conversation_store is not None and conversation_id:
            self._conversation_store.write_summary(
                conversation_id,
                (
                    f"agent_id={agent.agent_id} status={result.status.value} "
                    f"iterations={result.iterations}"
                ),
            )
        return result

    def _append_conversation_message(
        self,
        conversation_id: str | None,
        message: AgentMessageRecord,
    ) -> None:
        if self._conversation_store is None or not conversation_id:
            return
        self._conversation_store.append_message(conversation_id, message)


def _conversation_result_payload(result: AgentLoopResult) -> dict[str, Any]:
    if result.success:
        return {"success": True, "status": result.status.value, "output": result.output}
    return {
        "success": False,
        "status": result.status.value,
        "error": result.error,
        "verdict": result.verdict.to_dict() if result.verdict else None,
    }
