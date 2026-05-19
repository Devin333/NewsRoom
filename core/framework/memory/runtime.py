from __future__ import annotations

from typing import Any

from core.framework.memory.models import (
    MemoryQuery,
    MemoryRecallResult,
    MemoryRecord,
    MemoryWriteRequest,
    MemoryWriteResult,
    MemoryWriteMode,
)
from core.framework.memory.policy import DEFAULT_AGENT_MEMORY_POLICY, MemoryPolicy
from core.framework.memory.recall import SimpleMemoryRecallStrategy
from core.framework.memory.store import MemoryStore
from core.framework.memory.writer import MemoryWriter


class MemoryRuntime:
    def __init__(
        self,
        store: MemoryStore,
        *,
        policy: MemoryPolicy | None = None,
        recall_strategy: SimpleMemoryRecallStrategy | None = None,
        writer: MemoryWriter | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DEFAULT_AGENT_MEMORY_POLICY
        self.recall_strategy = recall_strategy or SimpleMemoryRecallStrategy()
        self.writer = writer or MemoryWriter()

    def recall(
        self,
        query: MemoryQuery | dict[str, Any] | str,
        *,
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecallResult:
        memory_query = _coerce_query(query)
        return self.recall_strategy.recall(
            memory_query,
            store=self.store,
            policy=policy or self.policy,
        )

    def write(
        self,
        request: MemoryWriteRequest | dict[str, Any] | None = None,
        *,
        records: list[MemoryRecord | dict[str, Any]] | None = None,
        mode: MemoryWriteMode | str = MemoryWriteMode.APPEND,
        actor: str | None = None,
        run_id: str | None = None,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        write_request = _coerce_write_request(
            request,
            records=records,
            mode=mode,
            actor=actor,
            run_id=run_id,
        )
        return self.writer.write(
            write_request,
            store=self.store,
            policy=policy or self.policy,
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def forget(self, memory_id: str) -> None:
        self.store.delete(memory_id)

    def consolidate(self, *args: Any, **kwargs: Any) -> MemoryWriteResult:
        raise NotImplementedError("memory consolidation strategy is not configured")


def _coerce_query(value: MemoryQuery | dict[str, Any] | str) -> MemoryQuery:
    if isinstance(value, MemoryQuery):
        return value
    if isinstance(value, dict):
        return MemoryQuery.from_dict(value)
    return MemoryQuery(query=str(value))


def _coerce_write_request(
    request: MemoryWriteRequest | dict[str, Any] | None,
    *,
    records: list[MemoryRecord | dict[str, Any]] | None,
    mode: MemoryWriteMode | str,
    actor: str | None,
    run_id: str | None,
) -> MemoryWriteRequest:
    if isinstance(request, MemoryWriteRequest):
        return request
    if isinstance(request, dict):
        return MemoryWriteRequest.from_dict(request)
    return MemoryWriteRequest(
        records=list(records or []),
        mode=mode,
        actor=actor,
        run_id=run_id,
    )

