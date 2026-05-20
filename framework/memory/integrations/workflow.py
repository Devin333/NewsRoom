from __future__ import annotations

from typing import Any, cast

from framework.memory.models import MemoryKind, MemoryQuery, MemoryRecord, MemoryRecallResult, MemoryScope, MemoryWriteResult
from framework.memory.policy import DEFAULT_WORKFLOW_MEMORY_POLICY, MemoryPolicy
from framework.memory.runtime import MemoryRuntime


class WorkflowMemoryAdapter:
    def recall_for_step(
        self,
        *,
        workflow_id: str,
        run_id: str,
        step_id: str,
        query_text: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        effective_policy = policy or DEFAULT_WORKFLOW_MEMORY_POLICY
        return runtime.recall(
            MemoryQuery(
                query=query_text,
                scopes=[MemoryScope.WORKFLOW, MemoryScope.SESSION, MemoryScope.GLOBAL],
                kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC],
                filters={"workflow_id": workflow_id, "step_id": step_id, "run_id": run_id},
                limit=effective_policy.max_recall_results,
                max_context_tokens=effective_policy.max_context_tokens,
            ),
            policy=effective_policy,
        )

    def write_step_memory(
        self,
        *,
        workflow_id: str,
        run_id: str,
        step_id: str,
        records: list[MemoryRecord],
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        prepared = [
            record.with_metadata(workflow_id=workflow_id, step_id=step_id).with_refs({"run_id": run_id})
            for record in records
        ]
        return runtime.write(
            records=cast(Any, prepared),
            actor=workflow_id,
            run_id=run_id,
            policy=policy or DEFAULT_WORKFLOW_MEMORY_POLICY,
        )

    def write_workflow_summary(
        self,
        *,
        workflow_id: str,
        run_id: str,
        summary: str,
        runtime: MemoryRuntime,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        return runtime.write(
            records=[
                MemoryRecord(
                    kind=MemoryKind.SEMANTIC,
                    scope=MemoryScope.WORKFLOW,
                    summary=f"Workflow summary for {workflow_id}",
                    content=summary,
                    metadata={"workflow_id": workflow_id},
                    refs={"run_id": run_id},
                )
            ],
            actor=workflow_id,
            run_id=run_id,
            policy=policy or DEFAULT_WORKFLOW_MEMORY_POLICY,
        )
