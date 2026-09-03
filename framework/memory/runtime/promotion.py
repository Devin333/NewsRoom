from __future__ import annotations

from dataclasses import replace

from framework.memory.models import MemoryKind, MemoryScope, MemoryWriteResult
from framework.memory.policy import DEFAULT_GRAPH_MEMORY_POLICY, MemoryPolicy
from framework.memory.stores import MemoryStore


class MemoryPromotionEngine:
    def promote(
        self,
        memory_id: str,
        *,
        store: MemoryStore,
        target_scope: MemoryScope | None = None,
        target_kind: MemoryKind | None = None,
        reason: str | None = None,
        policy: MemoryPolicy = DEFAULT_GRAPH_MEMORY_POLICY,
    ) -> MemoryWriteResult:
        record = store.get(memory_id)
        if record is None:
            return MemoryWriteResult(accepted_count=1, skipped_count=1, errors=[f"memory not found: {memory_id}"])
        promoted = self._promoted_record(record, target_scope=target_scope, target_kind=target_kind, reason=reason)
        try:
            policy.validate_write(promoted, operation="promote")
        except Exception as exc:
            return MemoryWriteResult(
                accepted_count=1,
                skipped_count=1,
                errors=[str(exc)],
            )
        store.update(memory_id, promoted.to_dict())
        return MemoryWriteResult(accepted_count=1, written_count=1, memory_ids=[memory_id])

    def _promoted_record(self, record, *, target_scope, target_kind, reason):
        metadata = dict(record.metadata)
        if reason:
            metadata["promotion_reason"] = reason
        return replace(
            record,
            scope=target_scope or MemoryScope.GLOBAL,
            kind=target_kind or record.kind,
            metadata=metadata,
        )
