from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Callable

import psycopg

from infrastructure.storage.postgres.dsn import normalize_dsn

from infrastructure.storage.lineage.models import LineageRef


ConnectionFactory = Callable[[], Any]


class PostgresLineageStore:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(normalize_dsn(dsn)))

    def record(self, ref: LineageRef) -> None:
        _validate_ref(ref)
        sql = """
        INSERT INTO lineage_refs (
            lineage_id, run_id, source_type, source_id, target_type, target_id,
            relation_type, created_at, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (lineage_id) DO UPDATE SET
            run_id = EXCLUDED.run_id,
            source_type = EXCLUDED.source_type,
            source_id = EXCLUDED.source_id,
            target_type = EXCLUDED.target_type,
            target_id = EXCLUDED.target_id,
            relation_type = EXCLUDED.relation_type,
            created_at = EXCLUDED.created_at,
            metadata = EXCLUDED.metadata,
            indexed_at = now()
        """
        self._execute(
            sql,
            (
                ref.lineage_id,
                ref.run_id,
                ref.source_type,
                ref.source_id,
                ref.target_type,
                ref.target_id,
                ref.relation_type,
                ref.created_at,
                _json(ref.metadata),
            ),
        )

    def record_many(self, refs: list[LineageRef]) -> list[None]:
        return [self.record(ref) for ref in refs]

    def list_by_run(self, run_id: str) -> list[LineageRef]:
        _validate_id(run_id, "run_id")
        return self._fetch_refs(_select_sql("WHERE run_id = %s"), (run_id,))

    def upstream(self, run_id: str, target_type: str, target_id: str) -> list[LineageRef]:
        _validate_id(run_id, "run_id")
        _validate_required(target_type, "target_type")
        _validate_required(target_id, "target_id")
        return self._fetch_refs(
            _select_sql("WHERE run_id = %s AND target_type = %s AND target_id = %s"),
            (run_id, target_type, target_id),
        )

    def downstream(self, run_id: str, source_type: str, source_id: str) -> list[LineageRef]:
        _validate_id(run_id, "run_id")
        _validate_required(source_type, "source_type")
        _validate_required(source_id, "source_id")
        return self._fetch_refs(
            _select_sql("WHERE run_id = %s AND source_type = %s AND source_id = %s"),
            (run_id, source_type, source_id),
        )

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
            connection.commit()

    def _fetch_refs(self, sql: str, params: tuple[Any, ...]) -> list[LineageRef]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return [_ref_from_row(row) for row in cursor.fetchall()]


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            lineage_id, run_id, source_type, source_id, target_type, target_id,
            relation_type, created_at, metadata
        FROM lineage_refs
        {where_clause}
        ORDER BY created_at ASC, lineage_id ASC
    """


def _ref_from_row(row: tuple[Any, ...]) -> LineageRef:
    return LineageRef(
        lineage_id=str(row[0]),
        run_id=str(row[1]),
        source_type=str(row[2]),
        source_id=str(row[3]),
        target_type=str(row[4]),
        target_id=str(row[5]),
        relation_type=str(row[6]),
        created_at=_timestamp(row[7]),
        metadata=_dict(row[8]),
    )


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _cursor_execute(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
    return cursor.execute(sql, params)


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    return dict(value)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _validate_ref(ref: LineageRef) -> None:
    _validate_id(ref.run_id, "run_id")
    _validate_required(ref.source_type, "source_type")
    _validate_required(ref.source_id, "source_id")
    _validate_required(ref.target_type, "target_type")
    _validate_required(ref.target_id, "target_id")
    _validate_required(ref.relation_type, "relation_type")


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")


def _validate_required(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
