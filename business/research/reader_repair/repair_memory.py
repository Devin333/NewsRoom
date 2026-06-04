from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.memory import MemoryWriteCandidate

from business.research.domain import stable_research_id
from business.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    ReaderRepairMemoryQuery,
    ReaderRepairStrategy,
)


class InMemoryReaderRepairMemory:
    def __init__(self) -> None:
        self.cases: dict[str, ReaderRepairCase] = {}
        self.strategies: dict[str, ReaderRepairStrategy] = {}
        self.write_candidates: dict[str, MemoryWriteCandidate] = {}

    def write_case(self, repair_case: ReaderRepairCase, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        self.cases[repair_case.repair_case_id] = repair_case
        return f"memory://{namespace}/case/{repair_case.repair_case_id}"

    def write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        self.strategies[strategy.strategy_id] = strategy
        return f"memory://{namespace}/strategy/{strategy.strategy_id}"

    def recall_cases(self, query: ReaderRepairMemoryQuery) -> tuple[ReaderRepairCase, ...]:
        _require_namespace(query.namespace)
        matches = [
            case
            for case in self.cases.values()
            if case.issue.issue_type == query.issue_type or case.issue.error_signature == query.error_signature
        ]
        return tuple(sorted(matches, key=lambda case: (not case.successful, case.repair_case_id)))

    def recall_strategies(self, issue_type: str, *, namespace: str = READER_REPAIR_NAMESPACE) -> list[ReaderRepairStrategy]:
        _require_namespace(namespace)
        return [
            strategy
            for strategy in self.strategies.values()
            if strategy.issue_type == issue_type and strategy.status in {"promoted_memory", "skill_candidate_ready", "validated"}
        ]

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        _require_namespace(candidate.namespace)
        self.write_candidates[candidate.candidate_id] = candidate
        return candidate


@dataclass
class ReaderRepairMemoryService:
    memory: InMemoryReaderRepairMemory
    namespace: str = READER_REPAIR_NAMESPACE
    write_refs: list[str] = field(default_factory=list)

    def build_query(self, issue: Any, *, source_format: str | None = None) -> ReaderRepairMemoryQuery:
        return ReaderRepairMemoryQuery.from_issue(issue, source_format=source_format)

    def recall(self, query: ReaderRepairMemoryQuery) -> dict[str, list[Any]]:
        cases = list(self.memory.recall_cases(query))
        strategies = self.memory.recall_strategies(query.issue_type, namespace=query.namespace)
        return {
            "similar_successful_cases": [case for case in cases if case.successful][: query.max_successful_cases],
            "similar_failed_cases": [case for case in cases if not case.successful][: query.max_failed_cases],
            "promoted_strategies": strategies[: query.max_strategies],
        }

    def memory_candidate_for_case(self, repair_case: ReaderRepairCase) -> MemoryWriteCandidate:
        return MemoryWriteCandidate(
            candidate_id=stable_research_id("repair_memory_write", repair_case.repair_case_id),
            namespace=self.namespace,
            content={"memory_kind": repair_case.memory_kind, "repair_case": repair_case.to_dict()},
            source_refs=tuple(repair_case.source_refs or repair_case.issue.source_refs),
            metadata={
                "issue_signature": repair_case.issue.error_signature,
                "successful": repair_case.successful,
                "active_skill_mutation": False,
            },
        )

    def commit_case(self, repair_case: ReaderRepairCase) -> str:
        candidate = self.memory.propose_write(self.memory_candidate_for_case(repair_case))
        ref = self.memory.write_case(repair_case, namespace=candidate.namespace)
        self.write_refs.append(ref)
        return ref


def _require_namespace(namespace: str) -> None:
    if namespace != READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory can only use research.reader_repair namespace")


__all__ = ["InMemoryReaderRepairMemory", "ReaderRepairMemoryService"]
