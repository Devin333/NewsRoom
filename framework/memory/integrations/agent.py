from __future__ import annotations

from typing import Any

from framework.memory.models import MemoryKind, MemoryQuery, MemoryRecord, MemoryRecallResult, MemoryScope, MemoryWriteResult
from framework.memory.policy import DEFAULT_AGENT_MEMORY_POLICY, DEFAULT_AGENT_MEMORY_WRITE_POLICY, MemoryPolicy
from framework.memory.runtime import MemoryRuntime


class AgentMemoryAdapter:
    def before_llm_call(
        self,
        *,
        agent_id: str,
        run_id: str,
        input_text: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy = DEFAULT_AGENT_MEMORY_POLICY,
    ) -> MemoryRecallResult:
        desired_scopes = [
            MemoryScope.SESSION,
            MemoryScope.AGENT,
            MemoryScope.WORKFLOW,
            MemoryScope.GLOBAL,
        ]
        return runtime.recall(
            MemoryQuery(
                query=input_text,
                scopes=_allowed_scopes(desired_scopes, policy=policy),
                kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC],
                filters={"agent_id": agent_id, "run_id": run_id} if run_id else {"agent_id": agent_id},
                limit=policy.max_recall_results,
                max_context_tokens=policy.max_context_tokens,
            ),
            policy=policy,
        )

    def after_tool_observation(
        self,
        *,
        agent_id: str,
        run_id: str,
        tool_name: str,
        observation: dict[str, Any],
        runtime: MemoryRuntime,
        policy: MemoryPolicy = DEFAULT_AGENT_MEMORY_WRITE_POLICY,
    ) -> MemoryWriteResult:
        return runtime.write(
            records=[
                MemoryRecord(
                    kind=MemoryKind.OBSERVATION,
                    scope=MemoryScope.AGENT,
                    summary=f"Tool observation from {tool_name}",
                    content=str(observation),
                    metadata={"agent_id": agent_id, "tool_name": tool_name},
                    refs={"run_id": run_id} if run_id else {},
                )
            ],
            actor=agent_id,
            run_id=run_id,
            policy=policy,
        )

    def after_final_output(
        self,
        *,
        agent_id: str,
        run_id: str,
        output: dict[str, Any],
        runtime: MemoryRuntime,
        policy: MemoryPolicy = DEFAULT_AGENT_MEMORY_WRITE_POLICY,
    ) -> MemoryWriteResult:
        return runtime.write(
            records=[
                MemoryRecord(
                    kind=MemoryKind.EPISODIC,
                    scope=MemoryScope.AGENT,
                    summary=f"Final output from {agent_id}",
                    content=str(output),
                    metadata={"agent_id": agent_id},
                    refs={"run_id": run_id} if run_id else {},
                )
            ],
            actor=agent_id,
            run_id=run_id,
            policy=policy,
        )


def _allowed_scopes(
    desired_scopes: list[MemoryScope],
    *,
    policy: MemoryPolicy,
) -> list[MemoryScope]:
    if not policy.allowed_scopes:
        return list(desired_scopes)
    allowed = set(policy.allowed_scopes)
    return [scope for scope in desired_scopes if scope in allowed]
