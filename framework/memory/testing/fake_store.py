from __future__ import annotations

from framework.memory.models import MemoryQuery, MemoryRecord, MemorySearchResult, MemoryWriteResult
from framework.memory.stores import InMemoryMemoryStore


class FakeMemoryStore(InMemoryMemoryStore):
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        super().__init__(records)
        self._next_write_error: Exception | None = None
        self._next_search_error: Exception | None = None

    def fail_next_write(self, error: Exception) -> None:
        self._next_write_error = error

    def fail_next_search(self, error: Exception) -> None:
        self._next_search_error = error

    def write_many(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        if self._next_write_error is not None:
            error = self._next_write_error
            self._next_write_error = None
            raise error
        return super().write_many(records)

    def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        if self._next_search_error is not None:
            error = self._next_search_error
            self._next_search_error = None
            raise error
        return super().search(query)
