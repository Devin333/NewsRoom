from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from framework.events.canonical import checksum_for
from framework.harness.runtime.materializer import (
    ResultAttemptLedgerPort,
    ResultCachePort,
    ResultCacheWriteRequest,
    ResultMaterializationOutcome,
    ResultQuotaPort,
    ResultQuotaReservation,
)
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    datetime_from_json,
    datetime_to_json,
    identifier,
    non_negative_int,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    NodeResultBinding,
    NodeResultEnvelope,
)
from framework.harness.runtime.result_policy import PersistenceBudgetSnapshot
from framework.shared.json import json_loads, stable_json_dumps
from framework.shared.time import utc_now


SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION = 1
DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN = 500 * 1024 * 1024
DEFAULT_MAX_ARTIFACTS_PER_RUN = 200
DEFAULT_BUSY_TIMEOUT_SECONDS = 30.0
_SYNCHRONOUS_POLICIES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS graph_result_store_metadata (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_attempts (
        binding_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        binding_json TEXT NOT NULL,
        binding_checksum TEXT NOT NULL,
        envelope_json TEXT NOT NULL,
        envelope_checksum TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_attempts_run_idx
    ON graph_result_attempts (tenant_id, run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_quota_reservations (
        reservation_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        reservation_key TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK (generation >= 1),
        reserved_bytes INTEGER NOT NULL CHECK (reserved_bytes >= 0),
        reserved_objects INTEGER NOT NULL CHECK (reserved_objects >= 1),
        reservation_checksum TEXT NOT NULL,
        actual_bytes INTEGER,
        actual_objects INTEGER,
        outcome TEXT,
        settlement_checksum TEXT,
        created_at TEXT NOT NULL,
        settled_at TEXT,
        UNIQUE (tenant_id, run_id, reservation_key, generation)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_quota_run_idx
    ON graph_result_quota_reservations (tenant_id, run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_result_cache (
        cache_key TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        request_json TEXT NOT NULL,
        request_checksum TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS graph_result_cache_expiry_idx
    ON graph_result_cache (tenant_id, expires_at)
    """,
)


class SQLiteGraphResultStore(
    ResultAttemptLedgerPort,
    ResultQuotaPort,
    ResultCachePort,
):
    """Transactional local result ledger, quota authority, and expiring cache."""

    def __init__(
        self,
        database: str | Path,
        *,
        max_materialized_bytes_per_run: int = (
            DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN
        ),
        max_artifacts_per_run: int = DEFAULT_MAX_ARTIFACTS_PER_RUN,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
        synchronous: str = "NORMAL",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        raw_database = str(database)
        if raw_database == ":memory:" or raw_database.startswith("file:"):
            raise ValueError("graph result storage requires a file-backed database")
        timeout = float(busy_timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError(
                "busy_timeout_seconds must be a finite non-negative number"
            )
        policy = str(synchronous).strip().upper()
        if policy not in _SYNCHRONOUS_POLICIES:
            raise ValueError("synchronous must be one of OFF, NORMAL, FULL, or EXTRA")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.max_materialized_bytes_per_run = _positive_int(
            max_materialized_bytes_per_run,
            "max_materialized_bytes_per_run",
        )
        self.max_artifacts_per_run = _positive_int(
            max_artifacts_per_run,
            "max_artifacts_per_run",
        )
        path = Path(database).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.database = str(path)
        self.busy_timeout_seconds = timeout
        self.synchronous = policy
        self._clock = clock
        self._initialize_schema()

    @property
    def durability_policy(self) -> Mapping[str, str | int]:
        return {
            "journal_mode": "WAL",
            "synchronous": self.synchronous,
            "busy_timeout_ms": int(self.busy_timeout_seconds * 1000),
            "host_scope": "single-host",
        }

    def get(self, binding: NodeResultBinding) -> NodeResultEnvelope | None:
        if not isinstance(binding, NodeResultBinding):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="attempt.binding",
            )
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_attempts WHERE binding_key = ?",
                    (_binding_key(binding),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "attempt.get",
            ) from exc
        if row is None:
            return None
        return _attempt_from_row(row, expected_binding=binding)

    def put(self, envelope: NodeResultEnvelope) -> NodeResultEnvelope:
        if not isinstance(envelope, NodeResultEnvelope):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="attempt.envelope",
            )
        binding = envelope.binding
        binding_payload = binding.to_dict()
        envelope_payload = envelope.to_dict()
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_attempts WHERE binding_key = ?",
                    (_binding_key(binding),),
                ).fetchone()
                if row is not None:
                    existing = _attempt_from_row(row, expected_binding=binding)
                    if existing != envelope:
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="attempt",
                        )
                    return existing
                connection.execute(
                    """
                    INSERT INTO graph_result_attempts (
                        binding_key, tenant_id, run_id, binding_json,
                        binding_checksum, envelope_json, envelope_checksum,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _binding_key(binding),
                        binding.tenant_id,
                        binding.run_id,
                        stable_json_dumps(binding_payload),
                        checksum_for(binding_payload),
                        stable_json_dumps(envelope_payload),
                        checksum_for(envelope_payload),
                        datetime_to_json(self._now()),
                    ),
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "attempt.put",
            ) from exc
        return envelope

    def reserve(
        self,
        *,
        tenant_id: str,
        run_id: str,
        reservation_key: str,
        requested_bytes: int,
        object_count: int,
    ) -> ResultQuotaReservation | None:
        tenant = identifier(tenant_id, "quota.tenant_id")
        run = identifier(run_id, "quota.run_id")
        key = reference(reservation_key, "quota.reservation_key")
        requested = non_negative_int(requested_bytes, "quota.requested_bytes")
        objects = _positive_int(object_count, "quota.object_count")
        try:
            with self._write() as connection:
                latest = connection.execute(
                    """
                    SELECT * FROM graph_result_quota_reservations
                    WHERE tenant_id = ? AND run_id = ? AND reservation_key = ?
                    ORDER BY generation DESC LIMIT 1
                    """,
                    (tenant, run, key),
                ).fetchone()
                generation = 1
                if latest is not None:
                    existing, existing_outcome = _reservation_from_row(latest)
                    if (
                        existing.reserved_bytes != requested
                        or existing.object_count != objects
                    ):
                        raise result_error(
                            GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                            field="quota.reservation",
                        )
                    if existing_outcome is not ResultMaterializationOutcome.FAILED:
                        return existing
                    generation = int(latest["generation"]) + 1

                usage = _quota_usage(
                    connection,
                    tenant_id=tenant,
                    run_id=run,
                )
                if (
                    usage.materialized_bytes + requested
                    > self.max_materialized_bytes_per_run
                    or usage.artifact_count + objects
                    > self.max_artifacts_per_run
                ):
                    return None
                reservation = ResultQuotaReservation(
                    reservation_id=_reservation_id(
                        tenant_id=tenant,
                        run_id=run,
                        reservation_key=key,
                        generation=generation,
                    ),
                    tenant_id=tenant,
                    run_id=run,
                    reservation_key=key,
                    reserved_bytes=requested,
                    object_count=objects,
                )
                payload = _reservation_payload(reservation)
                connection.execute(
                    """
                    INSERT INTO graph_result_quota_reservations (
                        reservation_id, tenant_id, run_id, reservation_key,
                        generation, reserved_bytes, reserved_objects,
                        reservation_checksum, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation.reservation_id,
                        tenant,
                        run,
                        key,
                        generation,
                        requested,
                        objects,
                        checksum_for(payload),
                        datetime_to_json(self._now()),
                    ),
                )
                return reservation
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
                "quota.reserve",
            ) from exc

    def settle(
        self,
        reservation: ResultQuotaReservation,
        *,
        actual_bytes: int,
        object_count: int,
        outcome: ResultMaterializationOutcome,
    ) -> None:
        if not isinstance(reservation, ResultQuotaReservation):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.reservation",
            )
        actual = non_negative_int(actual_bytes, "quota.actual_bytes")
        objects = non_negative_int(object_count, "quota.object_count")
        try:
            normalized_outcome = ResultMaterializationOutcome(outcome)
        except (TypeError, ValueError) as exc:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="quota.outcome",
            ) from exc
        if (
            actual > reservation.reserved_bytes
            or objects > reservation.object_count
            or (
                normalized_outcome is not ResultMaterializationOutcome.SUCCEEDED
                and (actual != 0 or objects != 0)
            )
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                field="quota.settlement",
            )
        try:
            with self._write() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM graph_result_quota_reservations
                    WHERE reservation_id = ?
                    """,
                    (reservation.reservation_id,),
                ).fetchone()
                if row is None:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.reservation",
                    )
                stored, stored_outcome = _reservation_from_row(row)
                if stored != reservation:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                        field="quota.reservation",
                    )
                settlement = _settlement_payload(
                    reservation,
                    actual_bytes=actual,
                    object_count=objects,
                    outcome=normalized_outcome,
                )
                if stored_outcome is not None:
                    if (
                        stored_outcome is not normalized_outcome
                        or int(row["actual_bytes"]) != actual
                        or int(row["actual_objects"]) != objects
                        or row["settlement_checksum"] != checksum_for(settlement)
                    ):
                        raise result_error(
                            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                            field="quota.settlement",
                        )
                    return
                settled_at = datetime_to_json(self._now())
                updated = connection.execute(
                    """
                    UPDATE graph_result_quota_reservations
                    SET actual_bytes = ?, actual_objects = ?, outcome = ?,
                        settlement_checksum = ?, settled_at = ?
                    WHERE reservation_id = ? AND outcome IS NULL
                    """,
                    (
                        actual,
                        objects,
                        normalized_outcome.value,
                        checksum_for(settlement),
                        settled_at,
                        reservation.reservation_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise result_error(
                        GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                        field="quota.settlement",
                    )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_SETTLEMENT_FAILED,
                "quota.settle",
            ) from exc

    def budget_snapshot(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> PersistenceBudgetSnapshot:
        tenant = identifier(tenant_id, "quota.tenant_id")
        run = identifier(run_id, "quota.run_id")
        try:
            with self._connection() as connection:
                return _quota_usage(
                    connection,
                    tenant_id=tenant,
                    run_id=run,
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
                "quota.usage",
            ) from exc

    def write(self, request: ResultCacheWriteRequest) -> str:
        if not isinstance(request, ResultCacheWriteRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="cache.request",
            )
        if not request.cache_key.startswith(f"cache://{request.tenant_id}/"):
            raise result_error(
                GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                field="cache.key",
            )
        now = self._now()
        if request.expires_at <= now:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_WRITE_FAILED,
                "cache.expires_at",
            )
        payload = _cache_request_payload(request)
        try:
            with self._write() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_cache WHERE cache_key = ?",
                    (request.cache_key,),
                ).fetchone()
                if row is not None:
                    existing = _cache_request_from_row(row)
                    if existing == request:
                        return request.cache_key
                    if existing.expires_at > now:
                        raise result_error(
                            GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID,
                            field="cache.key",
                        )
                    connection.execute(
                        "DELETE FROM graph_result_cache WHERE cache_key = ?",
                        (request.cache_key,),
                    )
                connection.execute(
                    """
                    INSERT INTO graph_result_cache (
                        cache_key, tenant_id, expires_at, request_json,
                        request_checksum, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.cache_key,
                        request.tenant_id,
                        datetime_to_json(request.expires_at),
                        stable_json_dumps(payload),
                        checksum_for(payload),
                        datetime_to_json(now),
                    ),
                )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_WRITE_FAILED,
                "cache.write",
            ) from exc
        return request.cache_key

    def read(self, ref: str) -> Mapping[str, Any]:
        cache_key = reference(ref, "cache.ref")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM graph_result_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.read",
            ) from exc
        if row is None:
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.ref",
            )
        request = _cache_request_from_row(row)
        if request.expires_at <= self._now():
            raise _error(
                GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
                "cache.expires_at",
            )
        return dict(request.payload)

    def verify_integrity(self) -> None:
        try:
            with self._connection() as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if result is None or str(result[0]).lower() != "ok":
                    raise _error(
                        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                        "sqlite.quick_check",
                    )
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.quick_check",
            ) from exc

    def _initialize_schema(self) -> None:
        try:
            with self._connection() as connection:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                if journal_mode.casefold() != "wal":
                    raise _error(
                        GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                        "sqlite.journal_mode",
                    )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _SCHEMA_STATEMENTS:
                        connection.execute(statement)
                    row = connection.execute(
                        "SELECT schema_version, created_at "
                        "FROM graph_result_store_metadata "
                        "WHERE singleton = 1"
                    ).fetchone()
                    if row is None:
                        connection.execute(
                            """
                            INSERT INTO graph_result_store_metadata (
                                singleton, schema_version, created_at
                            ) VALUES (1, ?, ?)
                            """,
                            (
                                SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION,
                                datetime_to_json(self._now()),
                            ),
                        )
                    elif int(row["schema_version"]) != (
                        SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION
                    ):
                        raise _error(
                            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                            "sqlite.schema_version",
                        )
                    else:
                        try:
                            datetime_from_json(
                                row["created_at"],
                                "sqlite.created_at",
                            )
                        except GraphArtifactResultError as exc:
                            raise _error(
                                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                                "sqlite.metadata",
                            ) from exc
                    connection.commit()
                except BaseException:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
        except GraphArtifactResultError:
            raise
        except sqlite3.Error as exc:
            raise _error(
                GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
                "sqlite.initialize",
            ) from exc
        self.verify_integrity()

    def _now(self) -> datetime:
        return aware_datetime(self._clock(), "clock")

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            f"PRAGMA busy_timeout={int(self.busy_timeout_seconds * 1000)}"
        )
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA synchronous={self.synchronous}")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise


def _binding_key(binding: NodeResultBinding) -> str:
    return checksum_for(binding.to_dict())


def _attempt_from_row(
    row: sqlite3.Row,
    *,
    expected_binding: NodeResultBinding,
) -> NodeResultEnvelope:
    try:
        binding_payload = json_loads(str(row["binding_json"]))
        envelope_payload = json_loads(str(row["envelope_json"]))
        if (
            not isinstance(binding_payload, Mapping)
            or not isinstance(envelope_payload, Mapping)
            or checksum_for(binding_payload) != row["binding_checksum"]
            or checksum_for(envelope_payload) != row["envelope_checksum"]
        ):
            raise ValueError("attempt checksum mismatch")
        binding = NodeResultBinding.from_dict(binding_payload)
        envelope = NodeResultEnvelope.from_dict(envelope_payload)
        datetime_from_json(row["created_at"], "attempt.created_at")
        if (
            binding != expected_binding
            or envelope.binding != binding
            or row["binding_key"] != _binding_key(binding)
            or row["tenant_id"] != binding.tenant_id
            or row["run_id"] != binding.run_id
        ):
            raise ValueError("attempt identity mismatch")
        return envelope
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.RESULT_LEDGER_FAILED,
            "attempt.record",
        ) from exc


def _reservation_id(
    *,
    tenant_id: str,
    run_id: str,
    reservation_key: str,
    generation: int,
) -> str:
    digest = hashlib.sha256(
        stable_json_dumps(
            {
                "tenant_id": tenant_id,
                "run_id": run_id,
                "reservation_key": reservation_key,
                "generation": generation,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"quota-reservation://{tenant_id}/{digest}/{generation}"


def _reservation_payload(
    reservation: ResultQuotaReservation,
) -> dict[str, str | int]:
    return {
        "reservation_id": reservation.reservation_id,
        "tenant_id": reservation.tenant_id,
        "run_id": reservation.run_id,
        "reservation_key": reservation.reservation_key,
        "reserved_bytes": reservation.reserved_bytes,
        "object_count": reservation.object_count,
    }


def _reservation_from_row(
    row: sqlite3.Row,
) -> tuple[ResultQuotaReservation, ResultMaterializationOutcome | None]:
    try:
        generation = int(row["generation"])
        reservation = ResultQuotaReservation(
            reservation_id=str(row["reservation_id"]),
            tenant_id=str(row["tenant_id"]),
            run_id=str(row["run_id"]),
            reservation_key=str(row["reservation_key"]),
            reserved_bytes=int(row["reserved_bytes"]),
            object_count=int(row["reserved_objects"]),
        )
        created_at = datetime_from_json(row["created_at"], "quota.created_at")
        if (
            generation < 1
            or reservation.reservation_id
            != _reservation_id(
                tenant_id=reservation.tenant_id,
                run_id=reservation.run_id,
                reservation_key=reservation.reservation_key,
                generation=generation,
            )
            or checksum_for(_reservation_payload(reservation))
            != row["reservation_checksum"]
        ):
            raise ValueError("reservation checksum mismatch")
        raw_outcome = row["outcome"]
        if raw_outcome is None:
            if any(
                row[field] is not None
                for field in (
                    "actual_bytes",
                    "actual_objects",
                    "settlement_checksum",
                    "settled_at",
                )
            ):
                raise ValueError("pending reservation contains settlement")
            return reservation, None
        outcome = ResultMaterializationOutcome(str(raw_outcome))
        actual = int(row["actual_bytes"])
        objects = int(row["actual_objects"])
        settled_at = datetime_from_json(row["settled_at"], "quota.settled_at")
        settlement = _settlement_payload(
            reservation,
            actual_bytes=actual,
            object_count=objects,
            outcome=outcome,
        )
        if (
            actual < 0
            or objects < 0
            or actual > reservation.reserved_bytes
            or objects > reservation.object_count
            or (
                outcome is not ResultMaterializationOutcome.SUCCEEDED
                and (actual != 0 or objects != 0)
            )
            or settled_at < created_at
            or checksum_for(settlement) != row["settlement_checksum"]
        ):
            raise ValueError("settlement checksum mismatch")
        return reservation, outcome
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.ARTIFACT_QUOTA_RESERVATION_FAILED,
            "quota.record",
        ) from exc


def _settlement_payload(
    reservation: ResultQuotaReservation,
    *,
    actual_bytes: int,
    object_count: int,
    outcome: ResultMaterializationOutcome,
) -> dict[str, Any]:
    return {
        "reservation_id": reservation.reservation_id,
        "actual_bytes": actual_bytes,
        "object_count": object_count,
        "outcome": outcome.value,
    }


def _quota_usage(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    run_id: str,
) -> PersistenceBudgetSnapshot:
    rows = connection.execute(
        """
        SELECT * FROM graph_result_quota_reservations
        WHERE tenant_id = ? AND run_id = ?
        ORDER BY reservation_key, generation
        """,
        (tenant_id, run_id),
    ).fetchall()
    materialized_bytes = 0
    artifact_count = 0
    for row in rows:
        reservation, outcome = _reservation_from_row(row)
        if outcome is None:
            materialized_bytes += reservation.reserved_bytes
            artifact_count += reservation.object_count
        elif outcome is ResultMaterializationOutcome.SUCCEEDED:
            materialized_bytes += int(row["actual_bytes"])
            artifact_count += int(row["actual_objects"])
    return PersistenceBudgetSnapshot(
        materialized_bytes=materialized_bytes,
        artifact_count=artifact_count,
    )


def _cache_request_payload(request: ResultCacheWriteRequest) -> dict[str, Any]:
    return {
        "cache_key": request.cache_key,
        "tenant_id": request.tenant_id,
        "payload": dict(request.payload),
        "media_type": request.media_type,
        "content_checksum": request.content_checksum,
        "byte_size": request.byte_size,
        "dependency_digest": request.dependency_digest,
        "policy_version": request.policy_version,
        "expires_at": datetime_to_json(request.expires_at),
    }


def _cache_request_from_row(row: sqlite3.Row) -> ResultCacheWriteRequest:
    try:
        payload = json_loads(str(row["request_json"]))
        if (
            not isinstance(payload, Mapping)
            or checksum_for(payload) != row["request_checksum"]
            or set(payload)
            != {
                "cache_key",
                "tenant_id",
                "payload",
                "media_type",
                "content_checksum",
                "byte_size",
                "dependency_digest",
                "policy_version",
                "expires_at",
            }
        ):
            raise ValueError("cache checksum mismatch")
        request = ResultCacheWriteRequest(
            cache_key=payload["cache_key"],
            tenant_id=payload["tenant_id"],
            payload=payload["payload"],
            media_type=payload["media_type"],
            content_checksum=payload["content_checksum"],
            byte_size=payload["byte_size"],
            dependency_digest=payload["dependency_digest"],
            policy_version=payload["policy_version"],
            expires_at=datetime_from_json(payload["expires_at"], "cache.expires_at"),
        )
        created_at = datetime_from_json(row["created_at"], "cache.created_at")
        if (
            row["cache_key"] != request.cache_key
            or row["tenant_id"] != request.tenant_id
            or row["expires_at"] != datetime_to_json(request.expires_at)
            or not request.cache_key.startswith(f"cache://{request.tenant_id}/")
            or request.expires_at <= created_at
        ):
            raise ValueError("cache identity mismatch")
        return request
    except Exception as exc:
        raise _error(
            GraphArtifactResultErrorCode.CACHE_READBACK_FAILED,
            "cache.record",
        ) from exc


def _positive_int(value: Any, field: str) -> int:
    normalized = non_negative_int(value, field)
    if normalized < 1:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field,
        )
    return normalized


def _error(
    code: GraphArtifactResultErrorCode,
    field: str,
) -> GraphArtifactResultError:
    return result_error(code, field=field)


__all__ = [
    "DEFAULT_MAX_ARTIFACTS_PER_RUN",
    "DEFAULT_MAX_MATERIALIZED_BYTES_PER_RUN",
    "SQLITE_GRAPH_RESULT_STORE_SCHEMA_VERSION",
    "SQLiteGraphResultStore",
]
