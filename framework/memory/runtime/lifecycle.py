from __future__ import annotations

from datetime import datetime
from typing import Any

from framework.memory.policy import MemoryPolicy
from framework.memory.stores import MemoryStore
from framework.shared.time import parse_datetime, utc_now


class MemoryLifecycleManager:
    def run(self, *, store: MemoryStore, policy: MemoryPolicy, now: datetime | None = None) -> dict[str, Any]:
        expired = self.expire_old_records(store=store, policy=policy, now=now)
        metrics = self.collect_metrics(store=store)
        return {"expired_memory_ids": expired, "metrics": metrics}

    def expire_old_records(self, *, store: MemoryStore, policy: MemoryPolicy, now: datetime | None = None) -> list[str]:
        actual_now = parse_datetime(now) or utc_now()
        records = _store_records(store)
        expired: list[str] = []
        for record in records:
            if record.expires_at is not None and record.expires_at <= actual_now:
                store.update(record.memory_id, record.mark_invalidated("expired", at=actual_now).to_dict())
                expired.append(record.memory_id)
        return expired

    def compact_records(self, *, store: MemoryStore, policy: MemoryPolicy) -> dict[str, Any]:
        return {"compacted": 0}

    def collect_metrics(self, *, store: MemoryStore) -> dict[str, Any]:
        records = _store_records(store)
        return {
            "total_records": len(records),
            "invalidated_records": sum(1 for record in records if record.is_invalidated()),
            "expired_records": sum(1 for record in records if record.is_expired()),
        }


def _store_records(store: MemoryStore):
    records = getattr(store, "records", None)
    if callable(records):
        return records()
    return []
