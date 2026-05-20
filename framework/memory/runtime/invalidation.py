from __future__ import annotations

from framework.memory.models import MemoryQuery, MemoryWriteResult
from framework.memory.stores import MemoryStore


class MemoryInvalidationEngine:
    def invalidate(self, memory_id: str, *, store: MemoryStore, reason: str) -> MemoryWriteResult:
        return self.invalidate_many([memory_id], store=store, reason=reason)

    def invalidate_many(self, memory_ids: list[str], *, store: MemoryStore, reason: str) -> MemoryWriteResult:
        written: list[str] = []
        skipped = 0
        for memory_id in memory_ids:
            record = store.get(memory_id)
            if record is None:
                skipped += 1
                continue
            store.update(memory_id, record.mark_invalidated(reason).to_dict())
            written.append(memory_id)
        return MemoryWriteResult(
            accepted_count=len(memory_ids),
            written_count=len(written),
            memory_ids=written,
            skipped_count=skipped,
        )

    def invalidate_by_query(self, query: MemoryQuery, *, store: MemoryStore, reason: str) -> MemoryWriteResult:
        return self.invalidate_many([result.memory_id for result in store.search(query)], store=store, reason=reason)
