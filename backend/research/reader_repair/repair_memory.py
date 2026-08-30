from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from framework.harness.memory import MemoryWriteCandidate

from backend.research.domain import stable_research_id
from backend.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    ReaderRepairMemoryQuery,
    ReaderRepairStrategy,
)
from backend.research.ports.repair_memory import ReaderRepairMemoryPort, ReaderRepairMemoryVersion


class InMemoryReaderRepairMemory:
    def __init__(self) -> None:
        self.cases: dict[str, ReaderRepairCase] = {}
        self.strategies: dict[str, ReaderRepairStrategy] = {}
        self.write_candidates: dict[str, MemoryWriteCandidate] = {}
        self.case_versions: dict[str, list[ReaderRepairMemoryVersion]] = {}
        self.strategy_versions: dict[str, list[ReaderRepairMemoryVersion]] = {}

    def write_case(self, repair_case: ReaderRepairCase, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        self.cases[repair_case.repair_case_id] = repair_case
        ref = _memory_ref(namespace, "case", repair_case.repair_case_id)
        self._append_version(
            self.case_versions,
            ref=ref,
            object_type="case",
            object_id=repair_case.repair_case_id,
            payload=repair_case.to_dict(),
            operation="upsert",
        )
        return ref

    def write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        self.strategies[strategy.strategy_id] = strategy
        ref = _memory_ref(namespace, "strategy", strategy.strategy_id)
        self._append_version(
            self.strategy_versions,
            ref=ref,
            object_type="strategy",
            object_id=strategy.strategy_id,
            payload=strategy.to_dict(),
            operation="upsert",
        )
        return ref

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

    def list_cases(self, *, namespace: str = READER_REPAIR_NAMESPACE) -> tuple[ReaderRepairCase, ...]:
        _require_namespace(namespace)
        return tuple(sorted(self.cases.values(), key=lambda case: case.repair_case_id))

    def list_case_versions(
        self,
        repair_case_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        _require_namespace(namespace)
        return tuple(self.case_versions.get(repair_case_id, ()))

    def rollback_case(
        self,
        repair_case_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
        version: int,
    ) -> str:
        _require_namespace(namespace)
        prior = _version_by_number(self.case_versions.get(repair_case_id, ()), version)
        case = ReaderRepairCase(**prior.payload)
        self.cases[repair_case_id] = case
        ref = _memory_ref(namespace, "case", repair_case_id)
        self._append_version(
            self.case_versions,
            ref=ref,
            object_type="case",
            object_id=repair_case_id,
            payload=case.to_dict(),
            operation="rollback",
        )
        return ref

    def list_strategy_versions(
        self,
        strategy_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        _require_namespace(namespace)
        return tuple(self.strategy_versions.get(strategy_id, ()))

    def rollback_strategy(
        self,
        strategy_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
        version: int,
    ) -> str:
        _require_namespace(namespace)
        prior = _version_by_number(self.strategy_versions.get(strategy_id, ()), version)
        strategy = ReaderRepairStrategy(**prior.payload)
        self.strategies[strategy_id] = strategy
        ref = _memory_ref(namespace, "strategy", strategy_id)
        self._append_version(
            self.strategy_versions,
            ref=ref,
            object_type="strategy",
            object_id=strategy_id,
            payload=strategy.to_dict(),
            operation="rollback",
        )
        return ref

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        _require_namespace(candidate.namespace)
        self.write_candidates[candidate.candidate_id] = candidate
        return candidate

    def _append_version(
        self,
        versions: dict[str, list[ReaderRepairMemoryVersion]],
        *,
        ref: str,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        operation: str,
    ) -> None:
        current = versions.setdefault(object_id, [])
        current.append(
            ReaderRepairMemoryVersion(
                memory_ref=ref,
                object_type=object_type,  # type: ignore[arg-type]
                object_id=object_id,
                version=len(current) + 1,
                operation=operation,
                payload=dict(payload),
            )
        )


@dataclass
class ReaderRepairMemoryService:
    memory: ReaderRepairMemoryPort
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

    def commit_case(
        self,
        repair_case: ReaderRepairCase,
        *,
        candidate: MemoryWriteCandidate | None = None,
    ) -> str:
        write_candidate = candidate or self.memory_candidate_for_case(repair_case)
        self.memory.propose_write(write_candidate)
        ref = self.memory.write_case(
            repair_case,
            namespace=write_candidate.namespace,
        )
        self.write_refs.append(ref)
        return ref

    def write_strategy(self, strategy: ReaderRepairStrategy) -> str:
        return self.memory.write_strategy(strategy, namespace=self.namespace)

    def list_cases(self) -> tuple[ReaderRepairCase, ...]:
        return self.memory.list_cases(namespace=self.namespace)


def _require_namespace(namespace: str) -> None:
    if namespace != READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory can only use research.reader_repair namespace")


def _memory_ref(namespace: str, object_type: str, object_id: str) -> str:
    return f"memory://{namespace}/{object_type}/{object_id}"


def _version_by_number(
    versions: Sequence[ReaderRepairMemoryVersion],
    version: int,
) -> ReaderRepairMemoryVersion:
    for candidate in versions:
        if candidate.version == version:
            return candidate
    raise KeyError(f"reader repair memory version not found: {version}")


__all__ = ["InMemoryReaderRepairMemory", "ReaderRepairMemoryService"]
