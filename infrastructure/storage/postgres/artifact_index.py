from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Callable

import psycopg

from framework.artifacts.paths import (
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from infrastructure.storage.postgres.dsn import normalize_dsn

from infrastructure.storage.artifacts.local_json import ArtifactIndexNotFoundError
from framework.artifacts.models import ArtifactRef


ConnectionFactory = Callable[[], Any]


class PostgresArtifactIndexStore:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(normalize_dsn(dsn)))

    def index_artifact(self, ref: ArtifactRef) -> None:
        _validate_ref(ref)
        sql = """
        INSERT INTO artifact_index (
            artifact_id, run_id, step_id, artifact_type, path, content_type,
            size_bytes, checksum, redacted, created_at, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (run_id, artifact_id) DO UPDATE SET
            step_id = EXCLUDED.step_id,
            artifact_type = EXCLUDED.artifact_type,
            path = EXCLUDED.path,
            content_type = EXCLUDED.content_type,
            size_bytes = EXCLUDED.size_bytes,
            checksum = EXCLUDED.checksum,
            redacted = EXCLUDED.redacted,
            created_at = EXCLUDED.created_at,
            metadata = EXCLUDED.metadata,
            indexed_at = now()
        """
        self._execute(
            sql,
            (
                ref.artifact_id,
                ref.run_id,
                ref.step_id,
                ref.artifact_type,
                ref.path,
                ref.content_type,
                ref.size_bytes,
                ref.checksum,
                ref.redacted,
                ref.created_at,
                _json(ref.metadata),
            ),
        )

    def get_artifact(self, run_id: str, artifact_id: str) -> ArtifactRef:
        _validate_id(run_id, "run_id")
        _require_artifact_id(artifact_id)
        row = self._fetch_one(
            _select_sql("WHERE run_id = %s AND artifact_id = %s"),
            (run_id, artifact_id),
        )
        if row is None:
            raise ArtifactIndexNotFoundError(
                f"artifact index record not found: {run_id}/{artifact_id}"
            )
        return _ref_from_row(row)

    def list_by_run(self, run_id: str) -> list[ArtifactRef]:
        _validate_id(run_id, "run_id")
        return self._fetch_refs(
            _select_sql("WHERE run_id = %s"),
            (run_id,),
        )

    def list_all(self) -> list[ArtifactRef]:
        return self._fetch_refs(_select_sql(""), ())

    def list_by_step(self, run_id: str, step_id: str) -> list[ArtifactRef]:
        _validate_id(run_id, "run_id")
        _validate_id(step_id, "step_id")
        return self._fetch_refs(
            _select_sql("WHERE run_id = %s AND step_id = %s"),
            (run_id, step_id),
        )

    def list_by_type(self, artifact_type: str, *, run_id: str | None = None) -> list[ArtifactRef]:
        _validate_required(artifact_type, "artifact_type")
        if run_id is not None:
            _validate_id(run_id, "run_id")
            return self._fetch_refs(
                _select_sql("WHERE artifact_type = %s AND run_id = %s"),
                (artifact_type, run_id),
            )
        return self._fetch_refs(
            _select_sql("WHERE artifact_type = %s"),
            (artifact_type,),
        )

    def delete_artifact(self, run_id: str, artifact_id: str) -> None:
        _validate_id(run_id, "run_id")
        _require_artifact_id(artifact_id)
        self._execute(
            "DELETE FROM artifact_index WHERE run_id = %s AND artifact_id = %s",
            (run_id, artifact_id),
        )

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
            connection.commit()

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return cursor.fetchone()

    def _fetch_refs(self, sql: str, params: tuple[Any, ...]) -> list[ArtifactRef]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, sql, params)
                return [_ref_from_row(row) for row in cursor.fetchall()]


def _select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            artifact_id, run_id, step_id, artifact_type, path, content_type,
            size_bytes, checksum, redacted, created_at, metadata
        FROM artifact_index
        {where_clause}
        ORDER BY run_id ASC, created_at ASC, artifact_id ASC
    """


def _ref_from_row(row: tuple[Any, ...]) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=str(row[0]),
        run_id=str(row[1]),
        step_id=_optional_str(row[2]),
        artifact_type=str(row[3]),
        path=str(row[4]),
        content_type=str(row[5]),
        size_bytes=_optional_int(row[6]),
        checksum=_optional_str(row[7]),
        redacted=bool(row[8]),
        created_at=_timestamp(row[9]),
        metadata=_dict(row[10]),
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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_ref(ref: ArtifactRef) -> None:
    _validate_id(ref.run_id, "run_id")
    _require_artifact_id(ref.artifact_id)
    if ref.step_id is not None:
        _validate_id(ref.step_id, "step_id")
    _validate_relative_path(ref.path)


def _validate_id(value: str, label: str) -> None:
    validate_artifact_path_segment(value, field=label)


def _validate_required(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")


def _require_artifact_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_id is required")
    return value


def _validate_relative_path(value: str) -> None:
    validate_relative_artifact_path(value, field="artifact path")
