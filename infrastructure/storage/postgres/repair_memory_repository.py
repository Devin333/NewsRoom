from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal

import psycopg

from framework.shared.json import to_jsonable

from infrastructure.storage.postgres.dsn import normalize_dsn


ConnectionFactory = Callable[[], Any]
ReaderRepairMemoryObjectType = Literal["case", "strategy"]
_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_READER_REPAIR_NAMESPACE = "research.reader_repair"


class PostgresReaderRepairMemoryCommitConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class PostgresReaderRepairMemoryVersion:
    memory_ref: str
    object_type: ReaderRepairMemoryObjectType
    object_id: str
    version: int
    operation: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PostgresReaderRepairMemoryObjectWrite:
    object_type: ReaderRepairMemoryObjectType
    object_id: str
    issue_type: str
    error_signature: str | None
    successful: bool | None
    status: str | None
    memory_kind: str
    payload: dict[str, Any]
    operation: str = "harness_commit"

    def __post_init__(self) -> None:
        if self.object_type not in {"case", "strategy"}:
            raise ValueError("reader repair memory object type is invalid")
        for field_name in ("object_id", "issue_type", "memory_kind", "operation"):
            _required_text(getattr(self, field_name), field_name)
        if not isinstance(self.payload, dict):
            raise TypeError("reader repair memory object payload must be a dictionary")
        object.__setattr__(self, "payload", _json_object_copy(self.payload))


@dataclass(frozen=True, slots=True)
class PostgresReaderRepairMemoryCommitRecord:
    idempotency_key: str
    request_checksum: str
    request_id: str
    run_id: str
    terminal_effect_id: str
    authorization_ref: str
    identity_scope_ref: str
    subject_scope_ref: str
    namespace: str
    case_object_id: str
    case_version: int
    strategy_versions: tuple[tuple[str, int], ...]
    committed_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "request_id",
            "run_id",
            "terminal_effect_id",
            "case_object_id",
        ):
            _required_text(getattr(self, field_name), field_name)
        for field_name in (
            "request_checksum",
            "authorization_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            value = _required_text(getattr(self, field_name), field_name)
            if _CHECKSUM_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
        if self.namespace != _READER_REPAIR_NAMESPACE:
            raise ValueError("reader repair memory commit namespace is invalid")
        if (
            isinstance(self.case_version, bool)
            or not isinstance(self.case_version, int)
            or self.case_version < 1
        ):
            raise ValueError("reader repair memory case version must be positive")
        strategy_versions = tuple(self.strategy_versions)
        strategy_ids: list[str] = []
        for object_id, version in strategy_versions:
            strategy_ids.append(_required_text(object_id, "strategy_object_id"))
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("reader repair memory strategy version must be positive")
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("reader repair memory strategy ids must be unique")
        object.__setattr__(self, "strategy_versions", strategy_versions)
        if not isinstance(self.committed_at, datetime):
            raise TypeError("reader repair memory commit timestamp must be datetime")
        if self.committed_at.tzinfo is None or self.committed_at.utcoffset() is None:
            raise ValueError("reader repair memory commit timestamp must be timezone-aware")
        object.__setattr__(self, "committed_at", self.committed_at.astimezone(UTC))


class PostgresReaderRepairMemoryRepository:
    """PostgreSQL payload store for reader repair memory objects.

    This infrastructure class intentionally stores and returns dictionaries. The
    business-domain mapping lives in the interface adapter so infrastructure
    does not import `business.*`.
    """

    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._dsn = normalize_dsn(dsn)
        self._conn = connection_factory or (lambda: psycopg.connect(self._dsn))

    def write_object(
        self,
        *,
        namespace: str,
        object_type: ReaderRepairMemoryObjectType,
        object_id: str,
        issue_type: str,
        error_signature: str | None,
        successful: bool | None,
        status: str | None,
        memory_kind: str,
        payload: dict[str, Any],
        operation: str = "upsert",
    ) -> str:
        payload_json = _json(payload)
        with self._conn() as conn:
            with conn.cursor() as cur:
                version = _next_version(cur, namespace=namespace, object_type=object_type, object_id=object_id)
                _write_object_version(
                    cur,
                    namespace=namespace,
                    write=PostgresReaderRepairMemoryObjectWrite(
                        object_type=object_type,
                        object_id=object_id,
                        issue_type=issue_type,
                        error_signature=error_signature,
                        successful=successful,
                        status=status,
                        memory_kind=memory_kind,
                        payload=payload,
                        operation=operation,
                    ),
                    version=version,
                    payload_json=payload_json,
                )
            conn.commit()
        return _memory_ref(namespace, object_type, object_id)

    def commit_bundle(
        self,
        *,
        idempotency_key: str,
        request_checksum: str,
        request_id: str,
        run_id: str,
        terminal_effect_id: str,
        authorization_ref: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        namespace: str,
        repair_case: PostgresReaderRepairMemoryObjectWrite,
        strategies: tuple[PostgresReaderRepairMemoryObjectWrite, ...],
    ) -> PostgresReaderRepairMemoryCommitRecord:
        identity = _commit_identity(
            idempotency_key=idempotency_key,
            request_checksum=request_checksum,
            request_id=request_id,
            run_id=run_id,
            terminal_effect_id=terminal_effect_id,
            authorization_ref=authorization_ref,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
            namespace=namespace,
        )
        writes = _validated_commit_writes(repair_case, strategies)
        with self._conn() as conn:
            try:
                with conn.cursor() as cur:
                    _acquire_transaction_lock(
                        cur,
                        f"reader-repair-memory-commit:{idempotency_key}",
                    )
                    existing = _read_commit_record(
                        cur,
                        idempotency_key=idempotency_key,
                    )
                    if existing is not None:
                        _assert_existing_commit(existing, identity, writes)
                        conn.commit()
                        return existing

                    for write in sorted(
                        writes,
                        key=lambda item: (item.object_type, item.object_id),
                    ):
                        _acquire_transaction_lock(
                            cur,
                            (
                                "reader-repair-memory-object:"
                                f"{namespace}:{write.object_type}:{write.object_id}"
                            ),
                        )

                    versions: list[tuple[PostgresReaderRepairMemoryObjectWrite, int]] = []
                    for write in writes:
                        version = _next_version(
                            cur,
                            namespace=namespace,
                            object_type=write.object_type,
                            object_id=write.object_id,
                        )
                        _write_object_version(
                            cur,
                            namespace=namespace,
                            write=write,
                            version=version,
                        )
                        versions.append((write, version))

                    committed_at = _insert_commit_header(cur, identity)
                    for ordinal, (write, version) in enumerate(versions):
                        _insert_commit_member(
                            cur,
                            idempotency_key=idempotency_key,
                            namespace=namespace,
                            ordinal=ordinal,
                            write=write,
                            version=version,
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return _commit_record(identity, versions, committed_at=committed_at)

    def recall_case_payloads(
        self,
        *,
        namespace: str,
        memory_kinds: list[str],
        issue_type: str,
        error_signature: str,
    ) -> tuple[dict[str, Any], ...]:
        sql = """
        SELECT payload
        FROM reader_repair_memory_objects
        WHERE namespace = %s
          AND object_type = 'case'
          AND memory_kind = ANY(%s)
          AND (issue_type = %s OR error_signature = %s)
        ORDER BY successful DESC NULLS LAST, object_id ASC
        """
        rows = self._fetch_all(sql, (namespace, memory_kinds, issue_type, error_signature))
        return tuple(_dict_payload(row[0]) for row in rows)

    def recall_strategy_payloads(
        self,
        *,
        namespace: str,
        issue_type: str,
        statuses: tuple[str, ...],
    ) -> tuple[dict[str, Any], ...]:
        if len(statuses) != 3:
            raise ValueError("reader repair strategy recall expects exactly three status filters")
        sql = """
        SELECT payload
        FROM reader_repair_memory_objects
        WHERE namespace = %s
          AND object_type = 'strategy'
          AND issue_type = %s
          AND status IN (%s, %s, %s)
        ORDER BY COALESCE((payload->>'confidence')::double precision, 0) DESC, object_id ASC
        """
        rows = self._fetch_all(sql, (namespace, issue_type, *statuses))
        return tuple(_dict_payload(row[0]) for row in rows)

    def list_case_payloads(self, *, namespace: str) -> tuple[dict[str, Any], ...]:
        sql = """
        SELECT payload
        FROM reader_repair_memory_objects
        WHERE namespace = %s AND object_type = 'case'
        ORDER BY updated_at DESC, object_id ASC
        """
        rows = self._fetch_all(sql, (namespace,))
        return tuple(_dict_payload(row[0]) for row in rows)

    def list_versions(
        self,
        *,
        namespace: str,
        object_type: ReaderRepairMemoryObjectType,
        object_id: str,
    ) -> tuple[PostgresReaderRepairMemoryVersion, ...]:
        sql = """
        SELECT version, operation, payload, created_at
        FROM reader_repair_memory_versions
        WHERE namespace = %s AND object_type = %s AND object_id = %s
        ORDER BY version ASC
        """
        rows = self._fetch_all(sql, (namespace, object_type, object_id))
        return tuple(
            PostgresReaderRepairMemoryVersion(
                memory_ref=_memory_ref(namespace, object_type, object_id),
                object_type=object_type,
                object_id=object_id,
                version=int(row[0]),
                operation=str(row[1]),
                payload=_dict_payload(row[2]),
            )
            for row in rows
        )

    def version_payload(
        self,
        *,
        namespace: str,
        object_type: ReaderRepairMemoryObjectType,
        object_id: str,
        version: int,
    ) -> dict[str, Any]:
        sql = """
        SELECT payload
        FROM reader_repair_memory_versions
        WHERE namespace = %s AND object_type = %s AND object_id = %s AND version = %s
        """
        row = self._fetch_one(sql, (namespace, object_type, object_id, version))
        if row is None:
            raise KeyError(f"reader repair memory version not found: {object_type}/{object_id}@{version}")
        return _dict_payload(row[0])

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> Any | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[Any]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())


def _next_version(
    cur: Any,
    *,
    namespace: str,
    object_type: ReaderRepairMemoryObjectType,
    object_id: str,
) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version), 0) + 1
        FROM reader_repair_memory_versions
        WHERE namespace = %s AND object_type = %s AND object_id = %s
        """,
        (namespace, object_type, object_id),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 1


def _write_object_version(
    cur: Any,
    *,
    namespace: str,
    write: PostgresReaderRepairMemoryObjectWrite,
    version: int,
    payload_json: str | None = None,
) -> None:
    serialized = payload_json or _json(write.payload)
    cur.execute(
        """
        INSERT INTO reader_repair_memory_objects (
            namespace, object_type, object_id, issue_type, error_signature,
            successful, status, memory_kind, payload, active_version
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
        ON CONFLICT (namespace, object_type, object_id) DO UPDATE SET
            issue_type = EXCLUDED.issue_type,
            error_signature = EXCLUDED.error_signature,
            successful = EXCLUDED.successful,
            status = EXCLUDED.status,
            memory_kind = EXCLUDED.memory_kind,
            payload = EXCLUDED.payload,
            active_version = EXCLUDED.active_version,
            updated_at = now()
        """,
        (
            namespace,
            write.object_type,
            write.object_id,
            write.issue_type,
            write.error_signature,
            write.successful,
            write.status,
            write.memory_kind,
            serialized,
            version,
        ),
    )
    cur.execute(
        """
        INSERT INTO reader_repair_memory_versions (
            namespace, object_type, object_id, version, operation, payload
        )
        VALUES (%s,%s,%s,%s,%s,%s::jsonb)
        """,
        (
            namespace,
            write.object_type,
            write.object_id,
            version,
            write.operation,
            serialized,
        ),
    )


def _commit_identity(**values: str) -> dict[str, str]:
    for field_name, value in values.items():
        _required_text(value, field_name)
    if values["namespace"] != _READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory commit namespace is invalid")
    for field_name in (
        "request_checksum",
        "authorization_ref",
        "identity_scope_ref",
        "subject_scope_ref",
    ):
        if _CHECKSUM_PATTERN.fullmatch(values[field_name]) is None:
            raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return dict(values)


def _validated_commit_writes(
    repair_case: PostgresReaderRepairMemoryObjectWrite,
    strategies: tuple[PostgresReaderRepairMemoryObjectWrite, ...],
) -> tuple[PostgresReaderRepairMemoryObjectWrite, ...]:
    if not isinstance(repair_case, PostgresReaderRepairMemoryObjectWrite):
        raise TypeError("repair_case must be PostgresReaderRepairMemoryObjectWrite")
    if repair_case.object_type != "case":
        raise ValueError("reader repair memory commit requires one case write")
    if not isinstance(strategies, tuple) or not all(
        isinstance(item, PostgresReaderRepairMemoryObjectWrite)
        for item in strategies
    ):
        raise TypeError("strategies must contain PostgresReaderRepairMemoryObjectWrite")
    if any(item.object_type != "strategy" for item in strategies):
        raise ValueError("reader repair memory commit strategy write type is invalid")
    writes = (repair_case, *strategies)
    operations = {item.operation for item in writes}
    if operations == {"harness_failure_diagnostic"}:
        if strategies or repair_case.successful is not False:
            raise ValueError(
                "reader repair failure diagnostic must contain one failed case only"
            )
    elif operations != {"harness_commit"}:
        raise ValueError(
            "reader repair memory bundle writes require one supported Harness operation"
        )
    identities = tuple((item.object_type, item.object_id) for item in writes)
    if len(identities) != len(set(identities)):
        raise ValueError("reader repair memory commit object identities must be unique")
    return writes


def _acquire_transaction_lock(cur: Any, lock_key: str) -> None:
    cur.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (lock_key,),
    )


def _read_commit_record(
    cur: Any,
    *,
    idempotency_key: str,
) -> PostgresReaderRepairMemoryCommitRecord | None:
    cur.execute(
        """
        SELECT request_checksum, request_id, run_id, terminal_effect_id,
               authorization_ref, identity_scope_ref, subject_scope_ref,
               namespace, committed_at
        FROM reader_repair_memory_commits
        WHERE idempotency_key = %s
        FOR UPDATE
        """,
        (idempotency_key,),
    )
    header = cur.fetchone()
    if header is None:
        return None
    cur.execute(
        """
        SELECT ordinal, object_type, object_id, version
        FROM reader_repair_memory_commit_members
        WHERE idempotency_key = %s
        ORDER BY ordinal ASC
        """,
        (idempotency_key,),
    )
    members = list(cur.fetchall())
    if not members or members[0][0:2] != (0, "case"):
        raise PostgresReaderRepairMemoryCommitConflictError(
            "reader repair memory commit members are incomplete"
        )
    if any(
        row[0] != index
        or (index > 0 and row[1] != "strategy")
        for index, row in enumerate(members)
    ):
        raise PostgresReaderRepairMemoryCommitConflictError(
            "reader repair memory commit member order is invalid"
        )
    return PostgresReaderRepairMemoryCommitRecord(
        idempotency_key=idempotency_key,
        request_checksum=header[0],
        request_id=header[1],
        run_id=header[2],
        terminal_effect_id=header[3],
        authorization_ref=header[4],
        identity_scope_ref=header[5],
        subject_scope_ref=header[6],
        namespace=header[7],
        case_object_id=members[0][2],
        case_version=members[0][3],
        strategy_versions=tuple(
            (row[2], row[3]) for row in members[1:]
        ),
        committed_at=header[8],
    )


def _assert_existing_commit(
    record: PostgresReaderRepairMemoryCommitRecord,
    identity: dict[str, str],
    writes: tuple[PostgresReaderRepairMemoryObjectWrite, ...],
) -> None:
    expected_identity = {
        field_name: identity[field_name]
        for field_name in (
            "idempotency_key",
            "request_checksum",
            "request_id",
            "run_id",
            "terminal_effect_id",
            "authorization_ref",
            "identity_scope_ref",
            "subject_scope_ref",
            "namespace",
        )
    }
    actual_identity = {
        field_name: getattr(record, field_name) for field_name in expected_identity
    }
    expected_members = tuple(
        (write.object_type, write.object_id) for write in writes
    )
    actual_members = (
        ("case", record.case_object_id),
        *(("strategy", object_id) for object_id, _version in record.strategy_versions),
    )
    if actual_identity != expected_identity or actual_members != expected_members:
        raise PostgresReaderRepairMemoryCommitConflictError(
            "reader repair memory idempotency key conflicts with stored commit"
        )


def _insert_commit_header(cur: Any, identity: dict[str, str]) -> datetime:
    cur.execute(
        """
        INSERT INTO reader_repair_memory_commits (
            idempotency_key, request_checksum, request_id, run_id,
            terminal_effect_id, authorization_ref, identity_scope_ref,
            subject_scope_ref, namespace
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING committed_at
        """,
        (
            identity["idempotency_key"],
            identity["request_checksum"],
            identity["request_id"],
            identity["run_id"],
            identity["terminal_effect_id"],
            identity["authorization_ref"],
            identity["identity_scope_ref"],
            identity["subject_scope_ref"],
            identity["namespace"],
        ),
    )
    row = cur.fetchone()
    if row is None or not isinstance(row[0], datetime):
        raise RuntimeError("reader repair memory commit timestamp was not returned")
    return row[0]


def _insert_commit_member(
    cur: Any,
    *,
    idempotency_key: str,
    namespace: str,
    ordinal: int,
    write: PostgresReaderRepairMemoryObjectWrite,
    version: int,
) -> None:
    cur.execute(
        """
        INSERT INTO reader_repair_memory_commit_members (
            idempotency_key, namespace, ordinal, object_type, object_id, version
        )
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (
            idempotency_key,
            namespace,
            ordinal,
            write.object_type,
            write.object_id,
            version,
        ),
    )


def _commit_record(
    identity: dict[str, str],
    versions: list[tuple[PostgresReaderRepairMemoryObjectWrite, int]],
    *,
    committed_at: datetime,
) -> PostgresReaderRepairMemoryCommitRecord:
    case_write, case_version = versions[0]
    return PostgresReaderRepairMemoryCommitRecord(
        **identity,
        case_object_id=case_write.object_id,
        case_version=case_version,
        strategy_versions=tuple(
            (write.object_id, version) for write, version in versions[1:]
        ),
        committed_at=committed_at,
    )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


def _dict_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("reader repair memory payload must be a JSON object")


def _json_object_copy(payload: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(to_jsonable(payload), ensure_ascii=False))
    if not isinstance(copied, dict):
        raise TypeError("reader repair memory object payload must be a dictionary")
    return copied


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(to_jsonable(payload), ensure_ascii=False, sort_keys=True)


def _memory_ref(namespace: str, object_type: ReaderRepairMemoryObjectType, object_id: str) -> str:
    return f"memory://{namespace}/{object_type}/{object_id}"


__all__ = [
    "PostgresReaderRepairMemoryCommitConflictError",
    "PostgresReaderRepairMemoryCommitRecord",
    "PostgresReaderRepairMemoryObjectWrite",
    "PostgresReaderRepairMemoryRepository",
    "PostgresReaderRepairMemoryVersion",
]
