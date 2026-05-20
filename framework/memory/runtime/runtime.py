from __future__ import annotations

from typing import Any

from framework.memory.models import (
    MemoryConsolidationRequest,
    MemoryConsolidationResult,
    MemoryForgetRequest,
    MemoryForgetResult,
    MemoryKind,
    MemoryQuery,
    MemoryRecallResult,
    MemoryRecord,
    MemoryScope,
    MemoryWriteMode,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from framework.memory.policy import DEFAULT_WORKFLOW_MEMORY_POLICY, MemoryPolicy
from framework.memory.runtime.context_assembler import MemoryContextAssembler
from framework.memory.runtime.consolidation import MemoryConsolidator
from framework.memory.runtime.forgetting import MemoryForgettingEngine
from framework.memory.runtime.invalidation import MemoryInvalidationEngine
from framework.memory.runtime.lifecycle import MemoryLifecycleManager
from framework.memory.runtime.promotion import MemoryPromotionEngine
from framework.memory.runtime.recall import MemoryRecallStrategy, SimpleMemoryRecallStrategy
from framework.memory.runtime.writer import MemoryWriter
from framework.memory.stores import MemoryStore


class MemoryRuntime:
    def __init__(
        self,
        store: MemoryStore,
        *,
        policy: MemoryPolicy | None = None,
        recall_strategy: MemoryRecallStrategy | None = None,
        assembler: MemoryContextAssembler | None = None,
        writer: MemoryWriter | None = None,
        consolidator: MemoryConsolidator | None = None,
        forgetting_engine: MemoryForgettingEngine | None = None,
        promotion_engine: MemoryPromotionEngine | None = None,
        invalidation_engine: MemoryInvalidationEngine | None = None,
        lifecycle_manager: MemoryLifecycleManager | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DEFAULT_WORKFLOW_MEMORY_POLICY
        self.recall_strategy = recall_strategy or SimpleMemoryRecallStrategy()
        self.assembler = assembler or MemoryContextAssembler()
        self.writer = writer or MemoryWriter()
        self.consolidator = consolidator or MemoryConsolidator()
        self.forgetting_engine = forgetting_engine or MemoryForgettingEngine()
        self.promotion_engine = promotion_engine or MemoryPromotionEngine()
        self.invalidation_engine = invalidation_engine or MemoryInvalidationEngine()
        self.lifecycle_manager = lifecycle_manager or MemoryLifecycleManager()

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
            assembler=self.assembler,
        )

    def write(
        self,
        request: MemoryWriteRequest | dict[str, Any] | None = None,
        *,
        records: list[MemoryRecord | dict[str, Any]] | None = None,
        mode: MemoryWriteMode | str = MemoryWriteMode.APPEND,
        actor: str | None = None,
        run_id: str | None = None,
        namespace: str | None = None,
        tenant_id: str | None = None,
        policy: MemoryPolicy | None = None,
    ) -> MemoryWriteResult:
        write_request = _coerce_write_request(
            request,
            records=records,
            mode=mode,
            actor=actor,
            run_id=run_id,
            namespace=namespace,
            tenant_id=tenant_id,
        )
        return self.writer.write(
            write_request,
            store=self.store,
            policy=policy or self.policy,
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def forget(
        self,
        request: MemoryForgetRequest | dict[str, Any] | str,
    ) -> MemoryForgetResult:
        if isinstance(request, str):
            self.store.delete(request)
            return MemoryForgetResult(forgotten_count=1, memory_ids=[request])
        forget_request = _coerce_forget_request(request)
        return self.forgetting_engine.forget(forget_request, store=self.store, policy=self.policy)

    def consolidate(
        self,
        request: MemoryConsolidationRequest | dict[str, Any],
    ) -> MemoryConsolidationResult:
        consolidation_request = _coerce_consolidation_request(request)
        return self.consolidator.consolidate(
            consolidation_request,
            store=self.store,
            policy=self.policy,
            writer=self.writer,
        )

    def promote(
        self,
        memory_id: str,
        *,
        target_scope: MemoryScope | None = None,
        target_kind: MemoryKind | None = None,
        reason: str | None = None,
    ) -> MemoryWriteResult:
        return self.promotion_engine.promote(
            memory_id,
            store=self.store,
            target_scope=target_scope,
            target_kind=target_kind,
            reason=reason,
        )

    def invalidate(self, memory_id: str, *, reason: str) -> MemoryWriteResult:
        return self.invalidation_engine.invalidate(memory_id, store=self.store, reason=reason)

    def invalidate_many(self, memory_ids: list[str], *, reason: str) -> MemoryWriteResult:
        return self.invalidation_engine.invalidate_many(memory_ids, store=self.store, reason=reason)

    def lifecycle(self) -> dict[str, Any]:
        return self.lifecycle_manager.run(store=self.store, policy=self.policy)


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
    namespace: str | None,
    tenant_id: str | None,
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
        namespace=namespace,
        tenant_id=tenant_id,
    )


def _coerce_forget_request(
    request: MemoryForgetRequest | dict[str, Any],
) -> MemoryForgetRequest:
    if isinstance(request, MemoryForgetRequest):
        return request
    return MemoryForgetRequest.from_dict(request)


def _coerce_consolidation_request(
    request: MemoryConsolidationRequest | dict[str, Any],
) -> MemoryConsolidationRequest:
    if isinstance(request, MemoryConsolidationRequest):
        return request
    return MemoryConsolidationRequest.from_dict(request)
