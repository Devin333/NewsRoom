from __future__ import annotations

from typing import Any

from core.framework.agent_loop.judge import OutputJudge
from core.framework.agent_loop.models import (
    AgentLoopMetrics,
    AgentLoopResult,
    AgentLoopStatus,
    AgentSpec,
    JudgeDecision,
    JudgeVerdict,
)
from core.framework.agent_loop.parser import AgentActionParser
from core.framework.agent_loop.prompt import PromptBuilder
from core.framework.llm import LLMClient
from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolObservation,
    ToolPolicy,
    ToolResult,
    ToolStatus,
)


class AgentLoop:
    def __init__(
        self,
        *,
        llm_client: LLMClient,
        tool_executor: ToolExecutor,
        prompt_builder: PromptBuilder | None = None,
        action_parser: AgentActionParser | None = None,
        output_judge: OutputJudge | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._action_parser = action_parser or AgentActionParser()
        self._output_judge = output_judge or OutputJudge()

    def run(self, agent: AgentSpec, inputs: dict[str, Any], tools: list[dict[str, Any]]) -> AgentLoopResult:
        metrics = AgentLoopMetrics()
        events: list[dict[str, Any]] = [
            {"event_type": "agent_started", "agent_id": agent.agent_id},
        ]
        feedback: str | None = None
        tool_observations: list[ToolObservation] = []
        called_tools: list[str] = []
        last_verdict: JudgeVerdict | None = None
        judge_retries = 0

        for iteration in range(1, agent.loop_policy.max_iterations + 1):
            request = self._prompt_builder.build(
                agent,
                inputs,
                feedback=feedback,
                tool_observations=[observation.to_dict() for observation in tool_observations],
                tools=tools,
            )
            response = self._llm_client.complete(request)
            metrics.llm_calls += 1
            metrics.add_usage(response.usage)
            events.append(
                {
                    "event_type": "llm_call",
                    "agent_id": agent.agent_id,
                    "iteration": iteration,
                    "token_usage": response.usage.to_dict(),
                }
            )

            try:
                action = self._action_parser.parse(response.content)
            except Exception as exc:
                feedback = f"parser error: {exc}"
                last_verdict = JudgeVerdict(
                    decision=JudgeDecision.RETRY,
                    confidence=0.0,
                    feedback=feedback,
                    schema_errors=[str(exc)],
                )
                judge_retries += 1
                events.append({"event_type": "judge_retry", "feedback": feedback})
                if judge_retries > agent.loop_policy.max_judge_retries:
                    return self._retry_exhausted(metrics, events, last_verdict, iteration)
                continue

            if action.action_type == "tool_call":
                tool_policy = agent.resolved_tool_policy()
                tool_call = ToolCall(
                    tool_name=action.tool_name or "",
                    arguments=action.tool_args,
                    requested_by_agent_id=agent.agent_id,
                )
                if metrics.tool_calls >= _max_tool_calls_per_agent(tool_policy):
                    observation = _blocked_tool_budget_observation(tool_call, tool_policy)
                else:
                    observation = self._execute_tool(tool_call, tool_policy)
                tool_observations.append(observation)
                called_tools.append(observation.call.tool_name)
                metrics.tool_calls += 1
                events.append(
                    {
                        "event_type": "tool_call",
                        "agent_id": agent.agent_id,
                        "tool_name": observation.call.tool_name,
                        "call_id": observation.call.call_id,
                    }
                )
                events.append(
                    {
                        "event_type": "tool_observation",
                        "agent_id": agent.agent_id,
                        "observation": observation.to_dict(),
                    }
                )
                if observation.status == ToolStatus.BLOCKED:
                    feedback = observation.result.error_message or "tool call blocked"
                elif observation.status == ToolStatus.FAILED:
                    feedback = observation.result.error_message or "tool call failed"
                else:
                    feedback = None
                continue

            verdict = self._output_judge.judge(
                agent=agent,
                action=action,
                called_tools=called_tools,
            )
            last_verdict = verdict
            if verdict.decision == JudgeDecision.ACCEPT:
                events.append(
                    {
                        "event_type": "final_output",
                        "agent_id": agent.agent_id,
                        "output_keys": sorted((action.output or {}).keys()),
                    }
                )
                return AgentLoopResult(
                    success=True,
                    status=AgentLoopStatus.ACCEPTED,
                    output=action.output or {},
                    verdict=verdict,
                    iterations=iteration,
                    metrics=metrics,
                    events=events,
                )

            if verdict.decision == JudgeDecision.BLOCK:
                events.append(
                    {
                        "event_type": "agent_blocked",
                        "agent_id": agent.agent_id,
                        "verdict": verdict.to_dict(),
                    }
                )
                return AgentLoopResult(
                    success=False,
                    status=AgentLoopStatus.BLOCKED,
                    verdict=verdict,
                    iterations=iteration,
                    metrics=metrics,
                    events=events,
                    error=verdict.feedback,
                )

            judge_retries += 1
            feedback = verdict.feedback or "output rejected by judge"
            events.append(
                {
                    "event_type": "judge_retry",
                    "agent_id": agent.agent_id,
                    "feedback": feedback,
                    "verdict": verdict.to_dict(),
                }
            )
            if judge_retries > agent.loop_policy.max_judge_retries:
                return self._retry_exhausted(metrics, events, verdict, iteration)

        return self._retry_exhausted(
            metrics,
            events,
            last_verdict,
            agent.loop_policy.max_iterations,
        )

    def _execute_tool(self, tool_call: ToolCall, tool_policy: ToolPolicy) -> ToolObservation:
        return self._tool_executor.execute(tool_call, tool_policy)

    def _retry_exhausted(
        self,
        metrics: AgentLoopMetrics,
        events: list[dict[str, Any]],
        verdict: JudgeVerdict | None,
        iterations: int,
    ) -> AgentLoopResult:
        events.append({"event_type": "agent_retry_exhausted"})
        return AgentLoopResult(
            success=False,
            status=AgentLoopStatus.RETRY_EXHAUSTED,
            verdict=verdict,
            iterations=iterations,
            metrics=metrics,
            events=events,
            error=verdict.feedback if verdict else "retry exhausted",
        )


def _max_tool_calls_per_agent(policy: ToolPolicy) -> int:
    return max(0, int(policy.max_tool_calls_per_agent))


def _blocked_tool_budget_observation(
    tool_call: ToolCall,
    policy: ToolPolicy,
) -> ToolObservation:
    return ToolObservation(
        call=tool_call,
        result=ToolResult(
            status=ToolStatus.BLOCKED,
            error_type="ToolPermissionError",
            error_message=(
                "agent exceeded max_tool_calls_per_agent "
                f"of {_max_tool_calls_per_agent(policy)}"
            ),
        ),
        elapsed_ms=0.0,
    )
