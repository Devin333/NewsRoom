from __future__ import annotations

from typing import Any

from core.framework.memory.models import (
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryRecallResult,
    MemoryScope,
    MemoryWriteResult,
)
from core.framework.memory.policy import (
    DEFAULT_AGENT_MEMORY_POLICY,
    DEFAULT_AGENT_MEMORY_WRITE_POLICY,
    DEFAULT_WORKFLOW_MEMORY_POLICY,
    MemoryPolicy,
)
from core.framework.memory.runtime import MemoryRuntime


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


class WorkflowMemoryAdapter:
    def recall_for_step(
        self,
        *,
        workflow_id: str,
        run_id: str,
        step_id: str,
        query_text: str,
        runtime: MemoryRuntime,
    ) -> MemoryRecallResult:
        return runtime.recall(
            MemoryQuery(
                query=query_text,
                scopes=[MemoryScope.WORKFLOW, MemoryScope.SESSION, MemoryScope.GLOBAL],
                kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC],
                filters={"workflow_id": workflow_id, "step_id": step_id, "run_id": run_id},
                limit=DEFAULT_WORKFLOW_MEMORY_POLICY.max_recall_results,
                max_context_tokens=DEFAULT_WORKFLOW_MEMORY_POLICY.max_context_tokens,
            ),
            policy=DEFAULT_WORKFLOW_MEMORY_POLICY,
        )

    def write_step_memory(
        self,
        *,
        workflow_id: str,
        run_id: str,
        step_id: str,
        records: list[MemoryRecord],
        runtime: MemoryRuntime,
    ) -> MemoryWriteResult:
        prepared = []
        for record in records:
            metadata = {
                **record.metadata,
                "workflow_id": workflow_id,
                "step_id": step_id,
            }
            refs = {**record.refs, "run_id": run_id}
            prepared.append(
                MemoryRecord(
                    memory_id=record.memory_id,
                    kind=record.kind,
                    scope=record.scope,
                    summary=record.summary,
                    content=record.content,
                    metadata=metadata,
                    refs=refs,
                    tags=record.tags,
                    confidence=record.confidence,
                    importance=record.importance,
                    actor=record.actor,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    expires_at=record.expires_at,
                )
            )
        return runtime.write(
            records=prepared,
            actor=workflow_id,
            run_id=run_id,
            policy=DEFAULT_WORKFLOW_MEMORY_POLICY,
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
