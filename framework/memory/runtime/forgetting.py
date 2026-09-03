from __future__ import annotations

from framework.memory.models import MemoryForgetRequest, MemoryForgetResult, MemoryQuery
from framework.memory.policy import MemoryPolicy
from framework.memory.stores import MemoryStore


class MemoryForgettingEngine:
    def forget(
        self,
        request: MemoryForgetRequest,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
    ) -> MemoryForgetResult:
        memory_ids = self._resolve_memory_ids(request, store)
        allowed_ids: list[str] = []
        warnings: list[str] = []
        for memory_id in memory_ids:
            record = store.get(memory_id)
            if record is None:
                continue
            try:
                policy.validate_operation("forget", record=record)
            except Exception as exc:
                warnings.append(str(exc))
                continue
            allowed_ids.append(memory_id)
        if request.hard_delete:
            forgotten = self._hard_delete(allowed_ids, store=store)
        else:
            forgotten = self._soft_delete(allowed_ids, store=store, reason=request.reason)
        skipped_count = max(0, len(memory_ids) - len(forgotten))
        return MemoryForgetResult(
            forgotten_count=len(forgotten),
            memory_ids=forgotten,
            skipped_count=skipped_count,
            warnings=warnings,
        )

    def _resolve_memory_ids(self, request: MemoryForgetRequest, store: MemoryStore) -> list[str]:
        memory_ids = list(dict.fromkeys(request.memory_ids))
        if request.filters:
            query = MemoryQuery(query="", filters=request.filters, limit=100, include_invalidated=True)
            memory_ids.extend(result.memory_id for result in store.search(query))
        return list(dict.fromkeys(memory_ids))

    def _soft_delete(self, memory_ids: list[str], *, store: MemoryStore, reason: str | None) -> list[str]:
        forgotten: list[str] = []
        for memory_id in memory_ids:
            record = store.get(memory_id)
            if record is None:
                continue
            store.update(memory_id, record.mark_invalidated(reason or "forgotten").to_dict())
            forgotten.append(memory_id)
        return forgotten

    def _hard_delete(self, memory_ids: list[str], *, store: MemoryStore) -> list[str]:
        forgotten: list[str] = []
        for memory_id in memory_ids:
            try:
                store.delete(memory_id)
            except NotImplementedError:
                continue
            forgotten.append(memory_id)
        return forgotten
