from __future__ import annotations

from datetime import datetime
from typing import Protocol

from framework.memory.models import MemoryQuery, MemorySearchResult


class TemporalMemoryStore(Protocol):
    def search_at_time(self, query: MemoryQuery, at: datetime) -> list[MemorySearchResult]:
        ...

__all__ = ["TemporalMemoryStore"]
