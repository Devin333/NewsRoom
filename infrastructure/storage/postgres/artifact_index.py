from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
from typing import Any, Callable

import psycopg

from framework.agent.artifacts.models import ArtifactRef, artifact_identity_key
from framework.agent.artifacts.paths import (
    validate_artifact_path_segment,
    validate_relative_artifact_path,
)
from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.shared.graph_identity import GraphRunIdentity, GraphStageIdentity
from infrastructure.storage.artifacts.local_json import ArtifactIndexNotFoundError
from infrastructure.storage.postgres.dsn import normalize_dsn


UTC = _tz.utc
ConnectionFactory = Callable[[], Any]


class PostgresArtifactIndexStore:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (
            lambda: psycopg.connect(normalize_dsn(dsn))
        )

    def index_artifact(self, ref: ArtifactRef) -> None:
        _validate_ref(ref)
        key = artifact_identity_key(ref)
        sql = """
        SELECT
            artifact_id, run_id, scope_kind, artifact_type, path, content_type,
            size_bytes, checksum, redacted, created_at, metadata,
            graph_id, graph_version, graph_ref, graph_checksum, node_id,
            node_instance_id, graph_checkpoint_ref, activity_id, attempt,
            artifact_identity_key
        FROM artifact_index
        WHERE artifact_identity_key = %s
        FOR UPDATE
        """
        insert_sql = """
        INSERT INTO artifact_index (
            artifact_id, run_id, scope_kind, artifact_identity_key,
            artifact_type, path, content_type, size_bytes, checksum, redacted,
            created_at, metadata, graph_id, graph_version, graph_ref,
            graph_checksum, node_id, node_instance_id, graph_checkpoint_ref,
            activity_id, attempt
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(cursor, "SELECT pg_advisory_xact_lock(hashtext(%s))", (key,))
                _cursor_execute(cursor, sql, (key,))
                row = cursor.fetchone()
                if row is not None:
                    existing = _ref_from_row(row)
                    if existing != ref:
                        raise ArtifactStoreMetadataError(
                            f"artifact index identity conflict: {ref.artifact_id}"
                        )
                    connection.commit()
                    return
                _cursor_execute(
                    cursor,
                    insert_sql,
                    (
                        ref.artifact_id,
                        ref.run_id,
                        ref.scope_kind,
                        key,
                        ref.artifact_type,
                        ref.path,
                        ref.content_type,
                        ref.size_bytes,
                        ref.checksum,
                        ref.redacted,
                        ref.created_at,
                        _json(ref.metadata),
                        ref.graph_id,
                        ref.graph_version,
                        ref.graph_ref,
                        ref.graph_checksum,
                        ref.node_id,
                        ref.node_instance_id,
                        ref.graph_checkpoint_ref,
                        ref.activity_id,
                        ref.attempt,
                    ),
                )
            connection.commit()

    def get_artifact(
        self,
        ref_or_run_id: ArtifactRef | str,
        artifact_id: str | None = None,
    ) -> ArtifactRef:
        ref = self._resolve_lookup(ref_or_run_id, artifact_id)
        _validate_ref(ref)
        row = self._fetch_one(
            _select_sql("WHERE artifact_identity_key = %s"),
            (artifact_identity_key(ref),),
        )
        if row is None:
            raise ArtifactIndexNotFoundError(
                f"artifact index record not found: {artifact_identity_key(ref)}"
            )
        stored = _ref_from_row(row)
        if stored != ref:
            raise ArtifactStoreMetadataError(
                f"artifact index identity mismatch: {ref.artifact_id}"
            )
        return stored

    def list_by_run(self, run_id: str) -> list[ArtifactRef]:
        _validate_id(run_id, "run_id")
        return self._fetch_refs(_select_sql("WHERE run_id = %s"), (run_id,))

    def list_all(self) -> list[ArtifactRef]:
        return self._fetch_refs(_select_sql(""), ())

    def list_by_node_instance(
        self,
        identity: GraphStageIdentity,
        *,
        activity_id: str | None = None,
        attempt: int | None = None,
    ) -> list[ArtifactRef]:
        identity = _require_stage_identity(identity)
        _validate_activity_filter(activity_id=activity_id, attempt=attempt)
        where = (
            "WHERE scope_kind = 'graph' AND run_id = %s AND graph_id = %s "
            "AND graph_version = %s AND graph_ref = %s AND graph_checksum = %s "
            "AND node_id = %s AND node_instance_id = %s"
        )
        params: tuple[Any, ...] = (
            identity.run_id,
            identity.graph_id,
            identity.graph_version,
            identity.graph_ref,
            identity.graph_checksum,
            identity.node_id,
            identity.node_instance_id,
        )
        if activity_id is not None:
            where += " AND activity_id = %s AND attempt = %s"
            params += (activity_id, attempt)
        return self._fetch_refs(_select_sql(where), params)

    def list_by_graph(self, identity: GraphRunIdentity) -> list[ArtifactRef]:
        if not isinstance(identity, GraphRunIdentity):
            raise TypeError("GraphRunIdentity is required")
        return self._fetch_refs(
            _select_sql(
                "WHERE scope_kind = 'graph' AND run_id = %s AND graph_id = %s "
                "AND graph_version = %s AND graph_ref = %s AND graph_checksum = %s"
            ),
            (
                identity.run_id,
                identity.graph_id,
                identity.graph_version,
                identity.graph_ref,
                identity.graph_checksum,
            ),
        )

    def list_by_type(
        self,
        artifact_type: str,
        *,
        run_id: str | None = None,
    ) -> list[ArtifactRef]:
        _validate_required(artifact_type, "artifact_type")
        if run_id is not None:
            _validate_id(run_id, "run_id")
            return self._fetch_refs(
                _select_sql("WHERE artifact_type = %s AND run_id = %s"),
                (artifact_type, run_id),
            )
        return self._fetch_refs(_select_sql("WHERE artifact_type = %s"), (artifact_type,))

    def delete_artifact(
        self,
        ref_or_run_id: ArtifactRef | str,
        artifact_id: str | None = None,
    ) -> None:
        ref = self._resolve_lookup(ref_or_run_id, artifact_id)
        _validate_ref(ref)
        key = artifact_identity_key(ref)
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                _cursor_execute(
                    cursor,
                    _select_sql("WHERE artifact_identity_key = %s") + " FOR UPDATE",
                    (key,),
                )
                row = cursor.fetchone()
                if row is None:
                    connection.commit()
                    return
                stored = _ref_from_row(row)
                if stored != ref:
                    raise ArtifactStoreMetadataError(
                        f"artifact index identity mismatch: {ref.artifact_id}"
                    )
                _cursor_execute(
                    cursor,
                    "DELETE FROM artifact_index WHERE artifact_identity_key = %s",
                    (key,),
                )
            connection.commit()

    def _resolve_lookup(
        self,
        ref_or_run_id: ArtifactRef | str,
        artifact_id: str | None,
    ) -> ArtifactRef:
        if isinstance(ref_or_run_id, ArtifactRef):
            if artifact_id is not None:
                raise TypeError("artifact_id cannot accompany an ArtifactRef")
            return ref_or_run_id
        if artifact_id is None:
            raise TypeError("an ArtifactRef or run_id plus artifact_id is required")
        _validate_id(ref_or_run_id, "run_id")
        _require_artifact_id(artifact_id)
        row = self._fetch_one(
            _select_sql(
                "WHERE scope_kind = 'standalone' AND run_id = %s "
                "AND artifact_id = %s"
            ),
            (ref_or_run_id, artifact_id),
        )
        if row is None:
            raise ArtifactIndexNotFoundError(
                f"artifact index record not found: {ref_or_run_id}/{artifact_id}"
            )
        return _ref_from_row(row)

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
            artifact_id, run_id, scope_kind, artifact_type, path, content_type,
            size_bytes, checksum, redacted, created_at, metadata,
            graph_id, graph_version, graph_ref, graph_checksum, node_id,
            node_instance_id, graph_checkpoint_ref, activity_id, attempt,
            artifact_identity_key
        FROM artifact_index
        {where_clause}
        ORDER BY run_id ASC, created_at ASC, artifact_id ASC
    """


def _ref_from_row(row: tuple[Any, ...]) -> ArtifactRef:
    if len(row) != 21:
        raise ArtifactStoreMetadataError(
            "artifact index row does not use the Graph-only schema"
        )
    try:
        ref = ArtifactRef(
            artifact_id=str(row[0]),
            run_id=str(row[1]),
            scope_kind=str(row[2]),
            artifact_type=str(row[3]),
            path=str(row[4]),
            content_type=str(row[5]),
            size_bytes=_optional_int(row[6]),
            checksum=_optional_str(row[7]),
            redacted=bool(row[8]),
            created_at=_timestamp(row[9]),
            metadata=_dict(row[10]),
            graph_id=_optional_str(row[11]),
            graph_version=_optional_str(row[12]),
            graph_ref=_optional_str(row[13]),
            graph_checksum=_optional_str(row[14]),
            node_id=_optional_str(row[15]),
            node_instance_id=_optional_str(row[16]),
            graph_checkpoint_ref=_optional_str(row[17]),
            activity_id=_optional_str(row[18]),
            attempt=_optional_int(row[19]),
        )
        if row[20] != artifact_identity_key(ref):
            raise ArtifactStoreMetadataError(
                "artifact index identity key does not match its Graph-only row"
            )
        return ref
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactStoreMetadataError(
            "artifact index row contains invalid Graph-only identity"
        ) from exc


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
    if not isinstance(ref, ArtifactRef):
        raise TypeError("artifact reference is required")
    _validate_id(ref.run_id, "run_id")
    validate_relative_artifact_path(ref.path, field="artifact path")


def _validate_id(value: str, label: str) -> None:
    validate_artifact_path_segment(value, field=label)


def _validate_required(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")


def _require_artifact_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_id is required")
    return value


def _require_stage_identity(value: GraphStageIdentity) -> GraphStageIdentity:
    if not isinstance(value, GraphStageIdentity):
        raise TypeError("GraphStageIdentity is required")
    return value


def _validate_activity_filter(*, activity_id: str | None, attempt: int | None) -> None:
    if (activity_id is None) != (attempt is None):
        raise ValueError("activity_id and attempt must be provided together")
    if activity_id is None:
        return
    _validate_id(activity_id, "activity_id")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")


__all__ = ["PostgresArtifactIndexStore"]
