from __future__ import annotations

from framework.harness.memory import MemoryWriteCandidate

from business.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    ReaderRepairMemoryQuery,
    ReaderRepairStrategy,
)
from business.research.ports import ReaderRepairMemoryVersion
from infrastructure.storage.postgres import PostgresReaderRepairMemoryRepository


_PROMOTED_STRATEGY_STATUSES = ("promoted_memory", "skill_candidate_ready", "validated")


class PostgresReaderRepairMemoryPort:
    def __init__(self, repository: PostgresReaderRepairMemoryRepository) -> None:
        self._repository = repository

    def write_case(self, repair_case: ReaderRepairCase, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        return self._write_case(repair_case, namespace=namespace, operation="upsert")

    def recall_cases(self, query: ReaderRepairMemoryQuery) -> tuple[ReaderRepairCase, ...]:
        _require_namespace(query.namespace)
        return tuple(
            ReaderRepairCase(**payload)
            for payload in self._repository.recall_case_payloads(
                namespace=query.namespace,
                memory_kinds=list(query.memory_kinds),
                issue_type=query.issue_type,
                error_signature=query.error_signature,
            )
        )

    def write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str = READER_REPAIR_NAMESPACE) -> str:
        _require_namespace(namespace)
        return self._write_strategy(strategy, namespace=namespace, operation="upsert")

    def recall_strategies(
        self,
        issue_type: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
    ) -> list[ReaderRepairStrategy]:
        _require_namespace(namespace)
        return [
            ReaderRepairStrategy(**payload)
            for payload in self._repository.recall_strategy_payloads(
                namespace=namespace,
                issue_type=issue_type,
                statuses=_PROMOTED_STRATEGY_STATUSES,
            )
        ]

    def list_cases(self, *, namespace: str = READER_REPAIR_NAMESPACE) -> tuple[ReaderRepairCase, ...]:
        _require_namespace(namespace)
        return tuple(
            ReaderRepairCase(**payload)
            for payload in self._repository.list_case_payloads(namespace=namespace)
        )

    def list_case_versions(
        self,
        repair_case_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        _require_namespace(namespace)
        return tuple(
            ReaderRepairMemoryVersion(
                memory_ref=version.memory_ref,
                object_type="case",
                object_id=version.object_id,
                version=version.version,
                operation=version.operation,
                payload=version.payload,
            )
            for version in self._repository.list_versions(
                namespace=namespace,
                object_type="case",
                object_id=repair_case_id,
            )
        )

    def rollback_case(
        self,
        repair_case_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
        version: int,
    ) -> str:
        _require_namespace(namespace)
        payload = self._repository.version_payload(
            namespace=namespace,
            object_type="case",
            object_id=repair_case_id,
            version=version,
        )
        return self._write_case(ReaderRepairCase(**payload), namespace=namespace, operation="rollback")

    def list_strategy_versions(
        self,
        strategy_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        _require_namespace(namespace)
        return tuple(
            ReaderRepairMemoryVersion(
                memory_ref=version.memory_ref,
                object_type="strategy",
                object_id=version.object_id,
                version=version.version,
                operation=version.operation,
                payload=version.payload,
            )
            for version in self._repository.list_versions(
                namespace=namespace,
                object_type="strategy",
                object_id=strategy_id,
            )
        )

    def rollback_strategy(
        self,
        strategy_id: str,
        *,
        namespace: str = READER_REPAIR_NAMESPACE,
        version: int,
    ) -> str:
        _require_namespace(namespace)
        payload = self._repository.version_payload(
            namespace=namespace,
            object_type="strategy",
            object_id=strategy_id,
            version=version,
        )
        return self._write_strategy(ReaderRepairStrategy(**payload), namespace=namespace, operation="rollback")

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        _require_namespace(candidate.namespace)
        return candidate

    def _write_case(self, repair_case: ReaderRepairCase, *, namespace: str, operation: str) -> str:
        return self._repository.write_object(
            namespace=namespace,
            object_type="case",
            object_id=repair_case.repair_case_id,
            issue_type=repair_case.issue.issue_type,
            error_signature=repair_case.issue.error_signature,
            successful=repair_case.successful,
            status=None,
            memory_kind=repair_case.memory_kind,
            payload=repair_case.to_dict(),
            operation=operation,
        )

    def _write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str, operation: str) -> str:
        return self._repository.write_object(
            namespace=namespace,
            object_type="strategy",
            object_id=strategy.strategy_id,
            issue_type=strategy.issue_type,
            error_signature=None,
            successful=None,
            status=strategy.status,
            memory_kind="procedural",
            payload=strategy.to_dict(),
            operation=operation,
        )


def _require_namespace(namespace: str) -> None:
    if namespace != READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory can only use research.reader_repair namespace")


__all__ = ["PostgresReaderRepairMemoryPort"]
