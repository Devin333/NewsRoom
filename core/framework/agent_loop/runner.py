from __future__ import annotations

from typing import Any

from core.framework.agent_loop.loop import AgentLoop
from core.framework.agent_loop.models import AgentLoopResult, AgentSpec
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.agent_loop.judge import OutputJudge
from core.framework.llm import GlobalBudgetTracker, LLMClient
from core.framework.tools import ToolExecutor, ToolRegistry
from storage.conversation import AgentMessageRecord, LocalJsonConversationStore


class AgentRunner:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        conversation_store: LocalJsonConversationStore | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._conversation_store = conversation_store
        self._global_budget_tracker = global_budget_tracker

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        *,
        conversation_id: str | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
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
        tools = self._tool_registry.export_schema_for_llm(
            agent.agent_id,
            agent.resolved_tool_policy(),
        )
        loop = AgentLoop(
            llm_client=self._llm_client,
            tool_executor=ToolExecutor(self._tool_registry),
            prompt_builder=PromptBuilder(),
            action_parser=AgentActionParser(),
            output_judge=OutputJudge(),
            global_budget_tracker=global_budget_tracker or self._global_budget_tracker,
        )
        result = loop.run(agent, inputs, tools)
        self._append_conversation_events(conversation_id, agent, result.events)
        self._append_conversation_diagnostics(conversation_id, agent, result)
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
                    f"iterations={result.iterations} "
                    f"stop_reason={_result_stop_reason(result)}"
                ),
            )
            self._compact_conversation_if_needed(conversation_id, agent)
        return result

    def _append_conversation_message(
        self,
        conversation_id: str | None,
        message: AgentMessageRecord,
    ) -> None:
        if self._conversation_store is None or not conversation_id:
            return
        self._conversation_store.append_message(conversation_id, message)

    def _append_conversation_events(
        self,
        conversation_id: str | None,
        agent: AgentSpec,
        events: list[dict[str, Any]],
    ) -> None:
        if self._conversation_store is None or not conversation_id:
            return
        for event in events:
            message = _conversation_message_from_event(conversation_id, agent, event)
            if message is not None:
                self._conversation_store.append_message(conversation_id, message)

    def _append_conversation_diagnostics(
        self,
        conversation_id: str | None,
        agent: AgentSpec,
        result: AgentLoopResult,
    ) -> None:
        if self._conversation_store is None or not conversation_id:
            return
        if result.diagnostics is None:
            return
        diagnostics = result.diagnostics.to_dict()
        trace_summary = diagnostics.get("trace_summary") or {}
        self._conversation_store.append_message(
            conversation_id,
            AgentMessageRecord(
                conversation_id=conversation_id,
                role="diagnostic",
                content={
                    "diagnostics": diagnostics,
                    "trace_summary": trace_summary,
                },
                agent_id=agent.agent_id,
                metadata={
                    "message_type": "agent_loop_diagnostics",
                    "status": result.status.value,
                    "stop_reason": diagnostics.get("stop_reason"),
                    "healthy": diagnostics.get("healthy"),
                    "severity": diagnostics.get("severity"),
                },
            ),
        )

    def _compact_conversation_if_needed(self, conversation_id: str, agent: AgentSpec) -> None:
        if self._conversation_store is None:
            return
        policy = agent.loop_policy
        if not policy.conversation_compaction_enabled:
            return
        messages = self._conversation_store.read_messages(conversation_id)
        if len(messages) <= policy.conversation_compaction_max_messages:
            return
        self._conversation_store.compact_messages(
            conversation_id,
            keep_last=policy.conversation_compaction_keep_last,
        )


def _conversation_result_payload(result: AgentLoopResult) -> dict[str, Any]:
    if result.success:
        return {
            "success": True,
            "status": result.status.value,
            "output": result.output,
            "diagnostics": result.diagnostics.to_dict() if result.diagnostics else None,
        }
    return {
        "success": False,
        "status": result.status.value,
        "error": result.error,
        "verdict": result.verdict.to_dict() if result.verdict else None,
        "diagnostics": result.diagnostics.to_dict() if result.diagnostics else None,
    }


def _conversation_message_from_event(
    conversation_id: str,
    agent: AgentSpec,
    event: dict[str, Any],
) -> AgentMessageRecord | None:
    event_type = str(event.get("event_type") or "")
    if event_type == "tool_observation":
        observation = event.get("observation")
        if not isinstance(observation, dict):
            return None
        return AgentMessageRecord(
            conversation_id=conversation_id,
            role="tool",
            content=dict(observation),
            agent_id=agent.agent_id,
            metadata={
                "message_type": "agent_tool_observation",
                "event_type": event_type,
                "tool_name": observation.get("tool_name"),
                "tool_call_id": observation.get("tool_call_id"),
                "status": observation.get("status"),
            },
        )
    if event_type == "judge_retry":
        return AgentMessageRecord(
            conversation_id=conversation_id,
            role="judge",
            content={
                "feedback": event.get("feedback"),
                "verdict": event.get("verdict"),
                "via_tool": event.get("via_tool"),
            },
            agent_id=agent.agent_id,
            metadata={
                "message_type": "agent_judge_retry",
                "event_type": event_type,
                "status": "retry",
            },
        )
    if event_type in {
        "agent_stalled",
        "agent_retry_exhausted",
        "agent_waiting_for_approval",
        "agent_blocked",
        "agent_failed",
    }:
        return AgentMessageRecord(
            conversation_id=conversation_id,
            role="diagnostic",
            content=dict(event),
            agent_id=agent.agent_id,
            metadata={
                "message_type": "agent_loop_stop_event",
                "event_type": event_type,
                "status": event_type.removeprefix("agent_"),
            },
        )
    return None


def _result_stop_reason(result: AgentLoopResult) -> str:
    if result.diagnostics is None:
        return "unknown"
    return result.diagnostics.stop_reason.value
