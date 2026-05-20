from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from framework.memory.models import MemoryKind, MemoryRecord, MemoryScope
from framework.shared.time import utc_now


@dataclass(frozen=True)
class MemoryRetentionPolicy:
    default_ttl_seconds: int | None = None
    persistent_scopes: tuple[MemoryScope, ...] = (
        MemoryScope.USER,
        MemoryScope.GLOBAL,
        MemoryScope.ORGANIZATION,
        MemoryScope.PROJECT,
    )

    def should_expire(self, record: MemoryRecord) -> bool:
        return record.expires_at is not None and record.expires_at <= utc_now()

    def expires_at_for(self, record: MemoryRecord):
        if record.expires_at is not None or record.scope in self.persistent_scopes:
            return record.expires_at
        if self.default_ttl_seconds is None:
            return None
        return record.created_at + timedelta(seconds=self.default_ttl_seconds)


@dataclass(frozen=True)
class MemoryPromotionPolicy:
    promotable_kinds: tuple[MemoryKind, ...] = (
        MemoryKind.CORE,
        MemoryKind.SEMANTIC,
        MemoryKind.REFLECTIVE,
        MemoryKind.PROCEDURAL,
        MemoryKind.PREFERENCE,
        MemoryKind.CONSTRAINT,
        MemoryKind.DECISION,
    )

    def can_promote(self, record: MemoryRecord) -> bool:
        return record.kind in self.promotable_kinds and not record.is_invalidated()
