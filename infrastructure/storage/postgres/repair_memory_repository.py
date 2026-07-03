from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

import psycopg

from framework.shared.json import to_jsonable

from infrastructure.storage.postgres.dsn import normalize_dsn


ConnectionFactory = Callable[[], Any]
ReaderRepairMemoryObjectType = Literal["case", "strategy"]


@dataclass(frozen=True)
class PostgresReaderRepairMemoryVersion:
    memory_ref: str
    object_type: ReaderRepairMemoryObjectType
    object_id: str
    version: int
    operation: str
    payload: dict[str, Any]


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
                        object_type,
                        object_id,
                        issue_type,
                        error_signature,
                        successful,
                        status,
                        memory_kind,
                        payload_json,
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
                    (namespace, object_type, object_id, version, operation, payload_json),
                )
            conn.commit()
        return _memory_ref(namespace, object_type, object_id)

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


def _dict_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("reader repair memory payload must be a JSON object")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(to_jsonable(payload), ensure_ascii=False, sort_keys=True)


def _memory_ref(namespace: str, object_type: ReaderRepairMemoryObjectType, object_id: str) -> str:
    return f"memory://{namespace}/{object_type}/{object_id}"


__all__ = ["PostgresReaderRepairMemoryRepository", "PostgresReaderRepairMemoryVersion"]
