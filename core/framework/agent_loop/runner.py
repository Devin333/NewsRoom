from __future__ import annotations

from typing import Any

from core.framework.agent_loop.loop import AgentLoop
from core.framework.agent_loop.models import AgentLoopResult, AgentSpec
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.agent_loop.judge import OutputJudge
from core.framework.agent_loop.subagents import SubAgentExecutor
from core.framework.llm import GlobalBudgetTracker, LLMClient
from core.framework.tools.executor import ToolExecutor
from core.framework.tools.registry import ToolRegistry
from storage.conversation import (
    AgentIterationCheckpoint,
    AgentMessageRecord,
    ConversationCursor,
    LocalJsonConversationStore,
)


class AgentRunner:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        conversation_store: LocalJsonConversationStore | None = None,
        global_budget_tracker: GlobalBudgetTracker | None = None,
        subagent_executor: SubAgentExecutor | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._conversation_store = conversation_store
        self._global_budget_tracker = global_budget_tracker
        self._subagent_executor = subagent_executor

    def run(
        self,
        agent: AgentSpec,
        inputs: dict[str, Any],
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
        step_id: str | None = None,
        workflow_checkpoint_id: str | None = None,
        resume_from_cursor: bool = False,
        global_budget_tracker: GlobalBudgetTracker | None = None,
    ) -> AgentLoopResult:
        loop_inputs = self._inputs_with_resume_context(
            inputs,
            conversation_id,
            agent_id=agent.agent_id,
            resume_from_cursor=resume_from_cursor,
        )
        self._append_conversation_message(
            conversation_id,
            AgentMessageRecord(
                conversation_id=conversation_id or "",
                role="user",
                content=inputs,
                agent_id=agent.agent_id,
                run_id=run_id,
                step_id=step_id,
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
            subagent_executor=self._subagent_executor,
        )
        result = loop.run(agent, loop_inputs, tools)
        self._append_conversation_events(
            conversation_id,
            agent,
            result.events,
            run_id=run_id,
            step_id=step_id,
        )
        self._append_conversation_diagnostics(
            conversation_id,
            agent,
            result,
            run_id=run_id,
            step_id=step_id,
        )
        self._append_conversation_message(
            conversation_id,
            AgentMessageRecord(
                conversation_id=conversation_id or "",
                role="assistant",
                content=_conversation_result_payload(result),
                agent_id=agent.agent_id,
                run_id=run_id,
                step_id=step_id,
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
            self._write_conversation_cursor(
                conversation_id,
                agent=agent,
                result=result,
                run_id=run_id,
                step_id=step_id,
                workflow_checkpoint_id=workflow_checkpoint_id,
            )
            self._write_iteration_checkpoint(
                conversation_id,
                agent=agent,
                result=result,
                run_id=run_id,
                step_id=step_id,
                workflow_checkpoint_id=workflow_checkpoint_id,
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

    def _append_conversation_events(
        self,
        conversation_id: str | None,
        agent: AgentSpec,
        events: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        step_id: str | None = None,
    ) -> None:
        if self._conversation_store is None or not conversation_id:
            return
        for event in events:
            message = _conversation_message_from_event(
                conversation_id,
                agent,
                event,
                run_id=run_id,
                step_id=step_id,
            )
            if message is not None:
                self._conversation_store.append_message(conversation_id, message)

    def _append_conversation_diagnostics(
        self,
        conversation_id: str | None,
        agent: AgentSpec,
        result: AgentLoopResult,
        *,
        run_id: str | None = None,
        step_id: str | None = None,
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
                run_id=run_id,
                step_id=step_id,
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

    def _inputs_with_resume_context(
        self,
        inputs: dict[str, Any],
        conversation_id: str | None,
        *,
        agent_id: str,
        resume_from_cursor: bool,
    ) -> dict[str, Any]:
        loop_inputs = dict(inputs)
        if not resume_from_cursor or self._conversation_store is None or not conversation_id:
            return loop_inputs
        cursor = self._conversation_store.read_cursor(conversation_id)
        if cursor is None:
            return loop_inputs
        cursor_agent_id = cursor.metadata.get("agent_id")
        if cursor_agent_id is not None and str(cursor_agent_id) != agent_id:
            raise ValueError(
                "conversation cursor agent_id mismatch: "
                f"{cursor_agent_id} != {agent_id}"
            )
        loop_inputs["conversation_cursor"] = cursor.to_dict()
        summary = self._conversation_store.get_summary(conversation_id)
        if summary is not None:
            loop_inputs["conversation_summary"] = summary
        checkpoint = self._conversation_store.read_iteration_checkpoint(conversation_id)
        if checkpoint is not None:
            checkpoint_agent_id = checkpoint.agent_id
            if checkpoint_agent_id != agent_id:
                raise ValueError(
                    "agent iteration checkpoint agent_id mismatch: "
                    f"{checkpoint_agent_id} != {agent_id}"
                )
            loop_inputs["agent_iteration_checkpoint"] = checkpoint.to_dict()
        return loop_inputs

    def _write_conversation_cursor(
        self,
        conversation_id: str,
        *,
        agent: AgentSpec,
        result: AgentLoopResult,
        run_id: str | None,
        step_id: str | None,
        workflow_checkpoint_id: str | None,
    ) -> None:
        if self._conversation_store is None:
            return
        messages = self._conversation_store.read_messages(conversation_id)
        if not messages:
            return
        latest = messages[-1]
        self._conversation_store.write_cursor(
            ConversationCursor(
                conversation_id=conversation_id,
                message_offset=len(messages) - 1,
                message_id=latest.message_id,
                run_id=run_id,
                step_id=step_id,
                workflow_checkpoint_id=workflow_checkpoint_id,
                metadata={
                    "agent_id": agent.agent_id,
                    "status": result.status.value,
                    "success": result.success,
                    "stop_reason": _result_stop_reason(result),
                    "iterations": result.iterations,
                    "message_type": latest.metadata.get("message_type"),
                },
            )
        )

    def _write_iteration_checkpoint(
        self,
        conversation_id: str,
        *,
        agent: AgentSpec,
        result: AgentLoopResult,
        run_id: str | None,
        step_id: str | None,
        workflow_checkpoint_id: str | None,
    ) -> None:
        if self._conversation_store is None:
            return
        messages = self._conversation_store.read_messages(conversation_id)
        latest_message_id = messages[-1].message_id if messages else None
        self._conversation_store.write_iteration_checkpoint(
            AgentIterationCheckpoint(
                conversation_id=conversation_id,
                agent_id=agent.agent_id,
                iteration=result.iterations,
                status=result.status.value,
                stop_reason=_result_stop_reason(result),
                run_id=run_id,
                step_id=step_id,
                workflow_checkpoint_id=workflow_checkpoint_id,
                message_id=latest_message_id,
                trace_summary=_trace_summary(result),
                diagnostics_summary=_diagnostics_summary(result),
                last_tool_observation=_last_tool_observation(result.events),
                llm_call_artifact_ids=[
                    artifact.artifact_id for artifact in result.llm_call_artifacts
                ],
                metadata=_iteration_checkpoint_metadata(result),
            )
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
    *,
    run_id: str | None = None,
    step_id: str | None = None,
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
            run_id=run_id,
            step_id=step_id,
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
            run_id=run_id,
            step_id=step_id,
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
            run_id=run_id,
            step_id=step_id,
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


def _trace_summary(result: AgentLoopResult) -> dict[str, Any]:
    summary = result.trace.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    if result.diagnostics is not None:
        return dict(result.diagnostics.trace_summary)
    return {}


def _diagnostics_summary(result: AgentLoopResult) -> dict[str, Any]:
    if result.diagnostics is None:
        return {
            "status": result.status.value,
            "stop_reason": "unknown",
            "summary": result.error,
            "healthy": result.success,
        }
    return {
        "status": result.diagnostics.status.value,
        "stop_reason": result.diagnostics.stop_reason.value,
        "summary": result.diagnostics.summary,
        "healthy": result.diagnostics.healthy,
        "severity": result.diagnostics.severity.value,
        "issues": [issue.to_dict() for issue in result.diagnostics.issues],
        "suggestions": list(result.diagnostics.suggestions),
    }


def _last_tool_observation(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") != "tool_observation":
            continue
        observation = event.get("observation")
        if not isinstance(observation, dict):
            return None
        result = observation.get("result")
        call = observation.get("call")
        output = result.get("output") if isinstance(result, dict) else None
        output_approval_id = output.get("approval_id") if isinstance(output, dict) else None
        return {
            "iteration": event.get("iteration"),
            "tool_name": observation.get("tool_name")
            or (call.get("tool_name") if isinstance(call, dict) else None),
            "tool_call_id": observation.get("tool_call_id")
            or (call.get("call_id") if isinstance(call, dict) else None),
            "status": observation.get("status"),
            "approval_id": (
                result.get("approval_id") if isinstance(result, dict) else None
            )
            or output_approval_id,
            "error_type": result.get("error_type") if isinstance(result, dict) else None,
        }
    return None


def _iteration_checkpoint_metadata(result: AgentLoopResult) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "success": result.success,
        "metrics": result.metrics.to_dict(),
        "event_count": len(result.events),
    }
    if result.diagnostics is not None:
        metadata["approval_ids"] = _approval_ids_from_diagnostics(result.diagnostics.to_dict())
    if result.error:
        metadata["error"] = result.error
    return metadata


def _approval_ids_from_diagnostics(diagnostics: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for issue in diagnostics.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        metadata = issue.get("metadata")
        if not isinstance(metadata, dict):
            continue
        approval_id = metadata.get("approval_id")
        if approval_id is not None:
            ids.append(str(approval_id))
    return ids
