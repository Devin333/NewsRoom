from __future__ import annotations

from typing import Protocol, runtime_checkable

from business.research.domain.reader_repair import ReaderRepairCase, ReaderRepairMemoryQuery, ReaderRepairStrategy


@runtime_checkable
class ReaderRepairMemoryPort(Protocol):
    def write_case(self, repair_case: ReaderRepairCase, *, namespace: str) -> str:
        ...

    def recall_cases(self, query: ReaderRepairMemoryQuery) -> tuple[ReaderRepairCase, ...]:
        ...

    def write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str) -> str:
        ...

    def recall_strategies(self, issue_type: str, *, namespace: str) -> list[ReaderRepairStrategy]:
        ...


__all__ = ["ReaderRepairMemoryPort"]
