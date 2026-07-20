"""SQLite-backed durable storage for Harness side-effect authority records."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectOutcome,
)
from framework.shared.json import json_loads, stable_json_dumps


SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION = 1
DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0
DEFAULT_SYNCHRONOUS = "FULL"
_SYNCHRONOUS_POLICIES = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})


_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS harness_side_effect_store_metadata (
    schema_version INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    CHECK (schema_version >= 1)
);

CREATE TABLE IF NOT EXISTS harness_side_effect_decisions (
    decision_ref TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    effect_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    command_ordinal INTEGER NOT NULL,
    identity_scope_ref TEXT NOT NULL,
    subject_scope_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    decision_json TEXT NOT NULL,
    UNIQUE (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref
    ),
    UNIQUE (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref,
        idempotency_key
    ),
    CHECK (length(decision_ref) = 71),
    CHECK (length(identity_scope_ref) = 71),
    CHECK (length(subject_scope_ref) = 71),
    CHECK (origin IN ('worker', 'controller_terminal')),
    CHECK (command_ordinal >= 0),
    CHECK (json_valid(decision_json))
);

CREATE INDEX IF NOT EXISTS idx_harness_side_effect_decisions_run
    ON harness_side_effect_decisions (run_id, command_ordinal, decision_id);
CREATE INDEX IF NOT EXISTS idx_harness_side_effect_decisions_scope
    ON harness_side_effect_decisions (
        identity_scope_ref, subject_scope_ref, effect_id
    );

CREATE TABLE IF NOT EXISTS harness_side_effect_attempts (
    effect_id TEXT PRIMARY KEY,
    decision_ref TEXT NOT NULL UNIQUE,
    identity_scope_ref TEXT NOT NULL,
    subject_scope_ref TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    attempt_limit INTEGER NOT NULL,
    FOREIGN KEY (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref
    ) REFERENCES harness_side_effect_decisions (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref
    )
        ON DELETE RESTRICT,
    CHECK (length(identity_scope_ref) = 71),
    CHECK (length(subject_scope_ref) = 71),
    CHECK (attempt_count >= 0),
    CHECK (attempt_limit >= 1),
    CHECK (attempt_count <= attempt_limit)
);

CREATE TABLE IF NOT EXISTS harness_side_effect_outcomes (
    outcome_ref TEXT PRIMARY KEY,
    outcome_id TEXT NOT NULL UNIQUE,
    effect_id TEXT NOT NULL UNIQUE,
    decision_ref TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    identity_scope_ref TEXT NOT NULL,
    subject_scope_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    disposition TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    FOREIGN KEY (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref,
        idempotency_key
    ) REFERENCES harness_side_effect_decisions (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref,
        idempotency_key
    )
        ON DELETE RESTRICT,
    CHECK (length(outcome_ref) = 71),
    CHECK (length(identity_scope_ref) = 71),
    CHECK (length(subject_scope_ref) = 71),
    CHECK (disposition IN ('candidate', 'prepared', 'quarantine', 'accepted')),
    CHECK (json_valid(outcome_json))
);

CREATE INDEX IF NOT EXISTS idx_harness_side_effect_outcomes_scope
    ON harness_side_effect_outcomes (
        identity_scope_ref, subject_scope_ref, effect_id
    );
"""


class SQLiteHarnessSideEffectStore:
    """Single-host durable implementation of ``HarnessSideEffectStorePort``.

    The adapter opens one short-lived connection per operation. Every mutation
    owns a ``BEGIN IMMEDIATE`` transaction so immutable records, retry-budget
    reservations, and disposition updates remain consistent across processes.
    """

    def __init__(
        self,
        database: str | Path | None = None,
        *,
        path: str | Path | None = None,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
        synchronous: str = DEFAULT_SYNCHRONOUS,
    ) -> None:
        if database is None:
            database = path
        elif path is not None:
            raise ValueError("provide either database or path, not both")
        if database is None:
            raise ValueError("a file-backed SQLite database path is required")
        raw_database = str(database)
        if raw_database == ":memory:" or raw_database.startswith("file:"):
            raise ValueError(
                "durable Harness side-effect storage requires a file-backed database"
            )
        timeout = float(busy_timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("busy_timeout_seconds must be a finite non-negative number")
        policy = str(synchronous).strip().upper()
        if policy not in _SYNCHRONOUS_POLICIES:
            raise ValueError("synchronous must be one of OFF, NORMAL, FULL, or EXTRA")

        path = Path(database).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _store_error(
                "side_effect_store_unavailable",
                "create SQLite Harness side-effect directory failed",
                database=str(path),
            ) from exc
        self.path = path
        self.database = str(path)
        self.busy_timeout_seconds = timeout
        self.synchronous = policy
        self._initialize_schema()

    @property
    def durability_policy(self) -> Mapping[str, str | int]:
        return {
            "journal_mode": "WAL",
            "synchronous": self.synchronous,
            "busy_timeout_ms": int(self.busy_timeout_seconds * 1000),
            "host_scope": "single-host",
        }

    def put_decision(
        self,
        decision: HarnessSideEffectDecision,
    ) -> HarnessSideEffectDecision:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None

        with self._write("persist Harness side-effect decision") as connection:
            rows = _unique_rows(
                connection.execute(
                    "SELECT * FROM harness_side_effect_decisions "
                    "WHERE decision_id = ? OR decision_ref = ? OR effect_id = ? "
                    "OR idempotency_key = ?",
                    (
                        decision.decision_id,
                        decision.checksum,
                        decision.effect_id,
                        decision.idempotency_key,
                    ),
                ).fetchall(),
                key="decision_ref",
            )
            if rows:
                existing = tuple(_decision_from_row(row) for row in rows)
                if any(candidate != decision for candidate in existing):
                    raise HarnessValidationError(
                        "side-effect decision identity is immutable"
                    )
                self._assert_attempt_ledger(connection, decision)
                return existing[0]

            connection.execute(
                "INSERT INTO harness_side_effect_decisions ("
                "decision_ref, decision_id, effect_id, run_id, origin, "
                "command_ordinal, identity_scope_ref, subject_scope_ref, "
                "idempotency_key, decision_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.checksum,
                    decision.decision_id,
                    decision.effect_id,
                    decision.run_id,
                    decision.origin.value,
                    decision.command_ordinal,
                    decision.identity_scope_ref,
                    decision.subject_scope_ref,
                    decision.idempotency_key,
                    stable_json_dumps(decision.to_dict()),
                ),
            )
            connection.execute(
                "INSERT INTO harness_side_effect_attempts ("
                "effect_id, decision_ref, identity_scope_ref, subject_scope_ref, "
                "attempt_count, attempt_limit"
                ") VALUES (?, ?, ?, ?, 0, ?)",
                (
                    decision.effect_id,
                    decision.checksum,
                    decision.identity_scope_ref,
                    decision.subject_scope_ref,
                    decision.effect_attempt_limit,
                ),
            )
        return decision

    def put_outcome(
        self,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        assert outcome.checksum is not None

        with self._write("persist Harness side-effect outcome") as connection:
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (outcome.decision_ref,),
            ).fetchone()
            if decision_row is None:
                raise HarnessValidationError(
                    "side-effect outcome has no durable authorization"
                )
            decision = _decision_from_row(decision_row)
            _assert_outcome_matches_decision(outcome, decision)

            rows = _unique_rows(
                connection.execute(
                    "SELECT * FROM harness_side_effect_outcomes "
                    "WHERE outcome_ref = ? OR outcome_id = ? OR effect_id = ? "
                    "OR idempotency_key = ?",
                    (
                        outcome.checksum,
                        outcome.outcome_id,
                        outcome.effect_id,
                        outcome.idempotency_key,
                    ),
                ).fetchall(),
                key="outcome_ref",
            )
            if rows:
                existing = tuple(_outcome_from_row(row) for row in rows)
                if any(candidate != outcome for candidate in existing):
                    raise HarnessValidationError(
                        "side-effect outcome identity is immutable"
                    )
                return existing[0]

            connection.execute(
                "INSERT INTO harness_side_effect_outcomes ("
                "outcome_ref, outcome_id, effect_id, decision_ref, run_id, "
                "identity_scope_ref, subject_scope_ref, idempotency_key, "
                "disposition, outcome_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    outcome.checksum,
                    outcome.outcome_id,
                    outcome.effect_id,
                    outcome.decision_ref,
                    outcome.run_id,
                    outcome.identity_scope_ref,
                    outcome.subject_scope_ref,
                    outcome.idempotency_key,
                    outcome.disposition.value,
                    stable_json_dumps(outcome.to_dict()),
                ),
            )
        return outcome

    def get_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
        idempotency_key: str,
    ) -> HarnessSideEffectOutcome | None:
        outcome = self._outcome_for_effect(effect_id)
        if outcome is None:
            return None
        _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
        if outcome.idempotency_key != idempotency_key:
            raise HarnessValidationError(
                "side-effect outcome idempotency identity mismatch"
            )
        return outcome

    def read_outcome(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        outcome = self._outcome_for_effect(effect_id)
        if outcome is None:
            return None
        _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
        return outcome

    def get_decision(
        self,
        decision_ref: str,
    ) -> HarnessSideEffectDecision | None:
        with self._read("read Harness side-effect decision") as connection:
            row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (decision_ref,),
            ).fetchone()
        return None if row is None else _decision_from_row(row)

    def list_decisions(
        self,
        *,
        run_id: str,
    ) -> tuple[HarnessSideEffectDecision, ...]:
        with self._read("list Harness side-effect decisions") as connection:
            rows = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE run_id = ? "
                "ORDER BY command_ordinal ASC, decision_id ASC",
                (run_id,),
            ).fetchall()
        return tuple(_decision_from_row(row) for row in rows)

    def reserve_attempt(self, decision: HarnessSideEffectDecision) -> int:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None

        with self._write("reserve Harness side-effect attempt") as connection:
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (decision.checksum,),
            ).fetchone()
            if decision_row is None or _decision_from_row(decision_row) != decision:
                raise HarnessValidationError(
                    "handler attempt requires the exact durable authorization"
                )
            ledger = self._assert_attempt_ledger(connection, decision)
            count = int(ledger["attempt_count"])
            limit = int(ledger["attempt_limit"])
            if count >= limit:
                raise _store_error(
                    "effect_retry_exhausted",
                    "side-effect retry budget is exhausted",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    attempt_limit=limit,
                )
            next_count = count + 1
            updated = connection.execute(
                "UPDATE harness_side_effect_attempts SET attempt_count = ? "
                "WHERE effect_id = ? AND decision_ref = ? AND attempt_count = ?",
                (
                    next_count,
                    decision.effect_id,
                    decision.checksum,
                    count,
                ),
            )
            if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE serializes writers
                raise _store_error(
                    "side_effect_store_conflict",
                    "side-effect attempt reservation conflicted",
                    effect_id=decision.effect_id,
                )
            return next_count

    def attempt_count(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> int:
        with self._read("read Harness side-effect attempt count") as connection:
            row = connection.execute(
                "SELECT * FROM harness_side_effect_attempts WHERE effect_id = ?",
                (effect_id,),
            ).fetchone()
            if row is None:
                decision_exists = connection.execute(
                    "SELECT 1 FROM harness_side_effect_decisions WHERE effect_id = ?",
                    (effect_id,),
                ).fetchone()
                if decision_exists is not None:
                    raise _corruption("side-effect decision has no attempt ledger")
                return 0
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (row["decision_ref"],),
            ).fetchone()
            if decision_row is None:
                raise _corruption("side-effect attempt has no decision")
            decision = _decision_from_row(decision_row)
            _assert_ledger_matches_decision(row, decision)
            if (
                row["identity_scope_ref"] != identity_scope_ref
                or row["subject_scope_ref"] != subject_scope_ref
            ):
                raise HarnessValidationError("side-effect attempt scope mismatch")
            return int(row["attempt_count"])

    def set_disposition(
        self,
        *,
        effect_id: str,
        disposition: HarnessSideEffectDisposition | str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectOutcome | None:
        try:
            next_disposition = HarnessSideEffectDisposition(disposition)
        except (TypeError, ValueError) as exc:
            raise HarnessValidationError("side-effect disposition is invalid") from exc

        with self._write("update Harness side-effect disposition") as connection:
            row = connection.execute(
                "SELECT * FROM harness_side_effect_outcomes WHERE effect_id = ?",
                (effect_id,),
            ).fetchone()
            if row is None:
                return None
            outcome = _outcome_from_row(row)
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (outcome.decision_ref,),
            ).fetchone()
            if decision_row is None:
                raise _corruption("side-effect outcome has no decision")
            _assert_stored_outcome_matches_decision(
                outcome,
                _decision_from_row(decision_row),
            )
            _assert_scope(outcome, identity_scope_ref, subject_scope_ref)
            if outcome.disposition is next_disposition:
                return outcome
            if next_disposition is HarnessSideEffectDisposition.ACCEPTED:
                raise HarnessValidationError(
                    "generic disposition mutation cannot publish an effect"
                )

            updated_outcome = replace(
                outcome,
                disposition=next_disposition,
                public_refs=(),
                reason_code=f"disposition_{next_disposition.value}",
                checksum=None,
            )
            assert updated_outcome.checksum is not None
            updated = connection.execute(
                "UPDATE harness_side_effect_outcomes SET outcome_ref = ?, "
                "disposition = ?, outcome_json = ? "
                "WHERE effect_id = ? AND outcome_ref = ?",
                (
                    updated_outcome.checksum,
                    updated_outcome.disposition.value,
                    stable_json_dumps(updated_outcome.to_dict()),
                    effect_id,
                    outcome.checksum,
                ),
            )
            if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE serializes writers
                raise _store_error(
                    "side_effect_store_conflict",
                    "side-effect disposition update conflicted",
                    effect_id=effect_id,
                )
            return updated_outcome

    def verify_integrity(self) -> None:
        with self._read("verify Harness side-effect store") as connection:
            connection.execute("BEGIN")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise _store_error(
                    "side_effect_store_corrupt",
                    "SQLite Harness side-effect store failed integrity verification",
                )
            decisions = {
                decision.checksum: decision
                for decision in (
                    _decision_from_row(row)
                    for row in connection.execute(
                        "SELECT * FROM harness_side_effect_decisions"
                    ).fetchall()
                )
            }
            for row in connection.execute(
                "SELECT * FROM harness_side_effect_attempts"
            ).fetchall():
                decision = decisions.get(row["decision_ref"])
                if decision is None:
                    raise _corruption("side-effect attempt has no decision")
                _assert_ledger_matches_decision(row, decision)
            for row in connection.execute(
                "SELECT * FROM harness_side_effect_outcomes"
            ).fetchall():
                outcome = _outcome_from_row(row)
                decision = decisions.get(outcome.decision_ref)
                if decision is None:
                    raise _corruption("side-effect outcome has no decision")
                _assert_stored_outcome_matches_decision(outcome, decision)
            connection.commit()

    def close(self) -> None:
        """Short-lived connections leave no instance resource to close."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def _outcome_for_effect(self, effect_id: str) -> HarnessSideEffectOutcome | None:
        with self._read("read Harness side-effect outcome") as connection:
            row = connection.execute(
                "SELECT * FROM harness_side_effect_outcomes WHERE effect_id = ?",
                (effect_id,),
            ).fetchone()
            if row is None:
                return None
            outcome = _outcome_from_row(row)
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (outcome.decision_ref,),
            ).fetchone()
            if decision_row is None:
                raise _corruption("side-effect outcome has no decision")
            _assert_stored_outcome_matches_decision(
                outcome,
                _decision_from_row(decision_row),
            )
            return outcome

    @staticmethod
    def _assert_attempt_ledger(
        connection: sqlite3.Connection,
        decision: HarnessSideEffectDecision,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM harness_side_effect_attempts WHERE effect_id = ?",
            (decision.effect_id,),
        ).fetchone()
        if row is None:
            raise _corruption("side-effect decision has no attempt ledger")
        _assert_ledger_matches_decision(row, decision)
        return row

    def _initialize_schema(self) -> None:
        try:
            with self._connection() as connection:
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                if journal_mode.lower() != "wal":
                    raise _store_error(
                        "side_effect_store_unavailable",
                        "SQLite Harness side-effect store requires WAL mode",
                        journal_mode=journal_mode,
                    )
                connection.executescript(_SCHEMA)
                connection.execute("BEGIN IMMEDIATE")
                metadata = connection.execute(
                    "SELECT schema_version FROM harness_side_effect_store_metadata "
                    "ORDER BY schema_version DESC LIMIT 1"
                ).fetchone()
                if metadata is None:
                    connection.execute(
                        "INSERT INTO harness_side_effect_store_metadata "
                        "(schema_version, created_at) "
                        "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                        (SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION,),
                    )
                elif int(metadata["schema_version"]) != SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION:
                    raise _store_error(
                        "side_effect_store_schema_unsupported",
                        "SQLite Harness side-effect schema version is unsupported",
                        schema_version=int(metadata["schema_version"]),
                    )
                connection.commit()
        except HarnessValidationError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error(exc, operation="initialize Harness side-effect store") from exc
        self.verify_integrity()

    def _open_connection(self) -> sqlite3.Connection:
        try:
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
        except sqlite3.Error as exc:
            raise _sqlite_error(exc, operation="open Harness side-effect store") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read(self, operation: str) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                yield connection
        except HarnessValidationError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error(exc, operation=operation) from exc

    @contextmanager
    def _write(self, operation: str) -> Iterator[sqlite3.Connection]:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except HarnessValidationError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error(exc, operation=operation) from exc


def _decision_from_row(row: sqlite3.Row) -> HarnessSideEffectDecision:
    try:
        payload = json_loads(str(row["decision_json"]))
        decision = HarnessSideEffectDecision.from_dict(payload)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise _corruption("stored side-effect decision is invalid") from exc
    expected = {
        "decision_ref": decision.checksum,
        "decision_id": decision.decision_id,
        "effect_id": decision.effect_id,
        "run_id": decision.run_id,
        "origin": decision.origin.value,
        "command_ordinal": decision.command_ordinal,
        "identity_scope_ref": decision.identity_scope_ref,
        "subject_scope_ref": decision.subject_scope_ref,
        "idempotency_key": decision.idempotency_key,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise _corruption("stored side-effect decision indexes do not match its payload")
    return decision


def _outcome_from_row(row: sqlite3.Row) -> HarnessSideEffectOutcome:
    try:
        payload = json_loads(str(row["outcome_json"]))
        outcome = HarnessSideEffectOutcome.from_dict(payload)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise _corruption("stored side-effect outcome is invalid") from exc
    expected = {
        "outcome_ref": outcome.checksum,
        "outcome_id": outcome.outcome_id,
        "effect_id": outcome.effect_id,
        "decision_ref": outcome.decision_ref,
        "run_id": outcome.run_id,
        "identity_scope_ref": outcome.identity_scope_ref,
        "subject_scope_ref": outcome.subject_scope_ref,
        "idempotency_key": outcome.idempotency_key,
        "disposition": outcome.disposition.value,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise _corruption("stored side-effect outcome indexes do not match its payload")
    return outcome


def _assert_ledger_matches_decision(
    row: sqlite3.Row,
    decision: HarnessSideEffectDecision,
) -> None:
    expected = {
        "effect_id": decision.effect_id,
        "decision_ref": decision.checksum,
        "identity_scope_ref": decision.identity_scope_ref,
        "subject_scope_ref": decision.subject_scope_ref,
        "attempt_limit": decision.effect_attempt_limit,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise _corruption("side-effect attempt ledger conflicts with its decision")
    count = int(row["attempt_count"])
    if count < 0 or count > decision.effect_attempt_limit:
        raise _corruption("side-effect attempt ledger count is invalid")


def _assert_outcome_matches_decision(
    outcome: HarnessSideEffectOutcome,
    decision: HarnessSideEffectDecision,
) -> None:
    if (
        outcome.decision_ref != decision.checksum
        or outcome.effect_id != decision.effect_id
        or outcome.run_id != decision.run_id
        or outcome.kind != decision.kind
        or outcome.handler != decision.handler
        or outcome.idempotency_key != decision.idempotency_key
        or outcome.identity_scope_ref != decision.identity_scope_ref
        or outcome.subject_scope_ref != decision.subject_scope_ref
        or outcome.atomic_group != decision.atomic_group
    ):
        raise HarnessValidationError(
            "side-effect outcome does not match authorization"
        )


def _assert_stored_outcome_matches_decision(
    outcome: HarnessSideEffectOutcome,
    decision: HarnessSideEffectDecision,
) -> None:
    try:
        _assert_outcome_matches_decision(outcome, decision)
    except HarnessValidationError as exc:
        raise _corruption("side-effect outcome conflicts with its decision") from exc


def _assert_scope(
    outcome: HarnessSideEffectOutcome,
    identity_scope_ref: str,
    subject_scope_ref: str,
) -> None:
    if (
        outcome.identity_scope_ref != identity_scope_ref
        or outcome.subject_scope_ref != subject_scope_ref
    ):
        raise HarnessValidationError("side-effect outcome scope mismatch")


def _unique_rows(
    rows: list[sqlite3.Row],
    *,
    key: str,
) -> tuple[sqlite3.Row, ...]:
    unique: dict[Any, sqlite3.Row] = {}
    for row in rows:
        unique[row[key]] = row
    return tuple(unique.values())


def _sqlite_error(exc: sqlite3.Error, *, operation: str) -> HarnessValidationError:
    if isinstance(exc, sqlite3.IntegrityError):
        return _store_error(
            "side_effect_store_conflict",
            f"{operation} violated the durable side-effect contract",
        )
    return _store_error(
        "side_effect_store_unavailable",
        f"{operation} failed",
    )


def _corruption(message: str) -> HarnessValidationError:
    return _store_error("side_effect_store_corrupt", message)


def _store_error(
    code: str,
    message: str,
    **details: Any,
) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_SECONDS",
    "DEFAULT_SYNCHRONOUS",
    "SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION",
    "SQLiteHarnessSideEffectStore",
]
