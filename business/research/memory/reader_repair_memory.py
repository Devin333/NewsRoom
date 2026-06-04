from __future__ import annotations

from business.research.domain.reader_repair import READER_REPAIR_NAMESPACE, ReaderRepairCase, ReaderRepairMemoryQuery, ReaderRepairStrategy
from business.research.reader_repair.repair_memory import InMemoryReaderRepairMemory


class ReaderRepairMemoryRepository(InMemoryReaderRepairMemory):
    namespace = READER_REPAIR_NAMESPACE

    def recall_successful_cases(self, query: ReaderRepairMemoryQuery) -> list[ReaderRepairCase]:
        return [case for case in self.recall_cases(query) if case.successful][: query.max_successful_cases]

    def recall_failed_cases(self, query: ReaderRepairMemoryQuery) -> list[ReaderRepairCase]:
        return [case for case in self.recall_cases(query) if not case.successful][: query.max_failed_cases]

    def recall_promoted_strategies(self, query: ReaderRepairMemoryQuery) -> list[ReaderRepairStrategy]:
        return self.recall_strategies(query.issue_type, namespace=query.namespace)[: query.max_strategies]


__all__ = ["ReaderRepairMemoryRepository"]
