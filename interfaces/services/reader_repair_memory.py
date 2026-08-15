from __future__ import annotations

from framework.harness.memory import MemoryWriteCandidate

from business.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    ReaderRepairMemoryQuery,
    ReaderRepairStrategy,
)
from business.research.ports import (
    ReaderRepairMemoryCommitReceipt,
    ReaderRepairMemoryCommitRequest,
    ReaderRepairMemoryVersion,
)
from business.research.ports.repair_memory import (
    reader_repair_case_memory_ref,
    reader_repair_strategy_memory_ref,
)
from infrastructure.storage.postgres import PostgresReaderRepairMemoryRepository
from infrastructure.storage.postgres.repair_memory_repository import (
    PostgresReaderRepairMemoryCommitRecord,
    PostgresReaderRepairMemoryObjectWrite,
)


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


class PostgresReaderRepairMemoryCommitPort:
    """Durable atomic writer used only by the Harness terminal handler."""

    def __init__(self, repository: PostgresReaderRepairMemoryRepository) -> None:
        self._repository = repository

    def commit(
        self,
        request: ReaderRepairMemoryCommitRequest,
    ) -> ReaderRepairMemoryCommitReceipt:
        if not isinstance(request, ReaderRepairMemoryCommitRequest):
            raise TypeError("request must be ReaderRepairMemoryCommitRequest")
        projection = request.projection
        request_checksum = _commit_request_checksum(request)
        record = self._repository.commit_bundle(
            idempotency_key=request.idempotency_key,
            request_checksum=request_checksum,
            request_id=request.request_id,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            identity_scope_ref=request.identity_scope_ref,
            subject_scope_ref=request.subject_scope_ref,
            namespace=projection.candidate.namespace,
            repair_case=_case_commit_write(projection.repair_case),
            strategies=tuple(
                _strategy_commit_write(strategy)
                for strategy in projection.strategies
            ),
        )
        _verify_commit_record(request, record)
        strategy_versions = tuple(
            version for _object_id, version in record.strategy_versions
        )
        return ReaderRepairMemoryCommitReceipt(
            receipt_id=f"reader-repair-memory-receipt:{request.request_id}",
            request_ref=request_checksum,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            idempotency_key=request.idempotency_key,
            namespace=projection.candidate.namespace,
            case_ref=reader_repair_case_memory_ref(
                projection.repair_case,
                version=record.case_version,
            ),
            case_version=record.case_version,
            strategy_refs=tuple(
                reader_repair_strategy_memory_ref(strategy, version=version)
                for strategy, version in zip(
                    projection.strategies,
                    strategy_versions,
                    strict=True,
                )
            ),
            strategy_versions=strategy_versions,
            committed_at=record.committed_at,
        )


def _case_commit_write(
    repair_case: ReaderRepairCase,
) -> PostgresReaderRepairMemoryObjectWrite:
    return PostgresReaderRepairMemoryObjectWrite(
        object_type="case",
        object_id=repair_case.repair_case_id,
        issue_type=repair_case.issue.issue_type,
        error_signature=repair_case.issue.error_signature,
        successful=repair_case.successful,
        status=None,
        memory_kind=repair_case.memory_kind,
        payload=repair_case.to_dict(),
    )


def _strategy_commit_write(
    strategy: ReaderRepairStrategy,
) -> PostgresReaderRepairMemoryObjectWrite:
    return PostgresReaderRepairMemoryObjectWrite(
        object_type="strategy",
        object_id=strategy.strategy_id,
        issue_type=strategy.issue_type,
        error_signature=None,
        successful=None,
        status=strategy.status,
        memory_kind="procedural",
        payload=strategy.to_dict(),
    )


def _commit_request_checksum(request: ReaderRepairMemoryCommitRequest) -> str:
    if request.checksum is None:
        raise ValueError("reader repair memory commit request has no checksum")
    return request.checksum


def _verify_commit_record(
    request: ReaderRepairMemoryCommitRequest,
    record: PostgresReaderRepairMemoryCommitRecord,
) -> None:
    if not isinstance(record, PostgresReaderRepairMemoryCommitRecord):
        raise TypeError("reader repair memory repository returned an invalid record")
    projection = request.projection
    expected_strategy_ids = tuple(
        strategy.strategy_id for strategy in projection.strategies
    )
    actual_strategy_ids = tuple(
        object_id for object_id, _version in record.strategy_versions
    )
    expected_identity = (
        request.idempotency_key,
        _commit_request_checksum(request),
        request.request_id,
        request.run_id,
        request.terminal_effect_id,
        request.authorization_ref,
        request.identity_scope_ref,
        request.subject_scope_ref,
        projection.candidate.namespace,
        projection.repair_case.repair_case_id,
        expected_strategy_ids,
    )
    actual_identity = (
        record.idempotency_key,
        record.request_checksum,
        record.request_id,
        record.run_id,
        record.terminal_effect_id,
        record.authorization_ref,
        record.identity_scope_ref,
        record.subject_scope_ref,
        record.namespace,
        record.case_object_id,
        actual_strategy_ids,
    )
    if actual_identity != expected_identity:
        raise ValueError(
            "reader repair memory repository record conflicts with commit request"
        )


def _require_namespace(namespace: str) -> None:
    if namespace != READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory can only use research.reader_repair namespace")


__all__ = [
    "PostgresReaderRepairMemoryCommitPort",
    "PostgresReaderRepairMemoryPort",
]
