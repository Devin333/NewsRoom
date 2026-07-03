from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from typing import Protocol, runtime_checkable

from framework.harness.memory import MemoryWriteCandidate

from business.research.domain.reader_repair import ReaderRepairCase, ReaderRepairMemoryQuery, ReaderRepairStrategy


@dataclass(frozen=True)
class ReaderRepairMemoryVersion:
    memory_ref: str
    object_type: Literal["case", "strategy"]
    object_id: str
    version: int
    operation: str
    payload: dict[str, Any]


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

    def list_cases(self, *, namespace: str) -> tuple[ReaderRepairCase, ...]:
        ...

    def list_case_versions(
        self,
        repair_case_id: str,
        *,
        namespace: str,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        ...

    def rollback_case(
        self,
        repair_case_id: str,
        *,
        namespace: str,
        version: int,
    ) -> str:
        ...

    def list_strategy_versions(
        self,
        strategy_id: str,
        *,
        namespace: str,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        ...

    def rollback_strategy(
        self,
        strategy_id: str,
        *,
        namespace: str,
        version: int,
    ) -> str:
        ...

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        ...


__all__ = ["ReaderRepairMemoryPort", "ReaderRepairMemoryVersion"]
