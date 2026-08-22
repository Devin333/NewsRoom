"""SQLite-backed durable storage for Harness side-effect authority records."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectAttemptLease,
    HarnessSideEffectAttemptStatus,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectOutcome,
    side_effect_record_identity_key,
)
from framework.shared.json import json_loads, stable_json_dumps
from framework.shared.time import format_datetime, utc_now


SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION = 3
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

CREATE TABLE IF NOT EXISTS harness_side_effect_attempt_leases (
    attempt_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    effect_id TEXT NOT NULL,
    decision_ref TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    identity_scope_ref TEXT NOT NULL,
    subject_scope_ref TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    fencing_generation INTEGER NOT NULL,
    acquired_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    termination_confirmed INTEGER NOT NULL,
    resolved_at TEXT,
    outcome_ref TEXT,
    attempt_json TEXT NOT NULL,
    FOREIGN KEY (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref,
        idempotency_key
    ) REFERENCES harness_side_effect_decisions (
        effect_id, decision_ref, identity_scope_ref, subject_scope_ref,
        idempotency_key
    )
        ON DELETE RESTRICT,
    FOREIGN KEY (outcome_ref)
        REFERENCES harness_side_effect_outcomes (outcome_ref)
        ON DELETE RESTRICT
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (effect_id, attempt),
    UNIQUE (effect_id, fencing_generation),
    CHECK (length(attempt_id) = 71),
    CHECK (length(lease_id) >= 1),
    CHECK (length(owner_id) >= 1),
    CHECK (length(identity_scope_ref) = 71),
    CHECK (length(subject_scope_ref) = 71),
    CHECK (attempt >= 1),
    CHECK (fencing_generation >= 1),
    CHECK (attempt = fencing_generation),
    CHECK (status IN ('active', 'terminated', 'indeterminate')),
    CHECK (termination_confirmed IN (0, 1)),
    CHECK (outcome_ref IS NULL OR length(outcome_ref) = 71),
    CHECK (
        (status = 'active' AND termination_confirmed = 0 AND resolved_at IS NULL)
        OR (status = 'terminated' AND termination_confirmed = 1 AND resolved_at IS NOT NULL)
        OR (status = 'indeterminate' AND termination_confirmed = 0 AND resolved_at IS NOT NULL)
    ),
    CHECK (status = 'terminated' OR outcome_ref IS NULL),
    CHECK (json_valid(attempt_json))
);

CREATE INDEX IF NOT EXISTS idx_harness_side_effect_attempt_leases_effect
    ON harness_side_effect_attempt_leases (effect_id, fencing_generation DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_harness_side_effect_attempt_one_unresolved
    ON harness_side_effect_attempt_leases (effect_id)
    WHERE status IN ('active', 'indeterminate');

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
        attempt_lease_seconds: float = 30.0,
        clock: Callable[[], datetime] = utc_now,
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
            raise ValueError(
                "busy_timeout_seconds must be a finite non-negative number"
            )
        policy = str(synchronous).strip().upper()
        if policy not in _SYNCHRONOUS_POLICIES:
            raise ValueError("synchronous must be one of OFF, NORMAL, FULL, or EXTRA")
        lease_seconds = float(attempt_lease_seconds)
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("attempt_lease_seconds must be a finite positive number")
        if not callable(clock):
            raise TypeError("clock must be callable")

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
        self.attempt_lease_seconds = lease_seconds
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

    def put_decision(
        self,
        decision: HarnessSideEffectDecision,
    ) -> HarnessSideEffectDecision:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None

        with self._write("persist Harness side-effect decision") as connection:
            identity_key = side_effect_record_identity_key(decision)
            rows = _unique_rows(
                connection.execute(
                    "SELECT * FROM harness_side_effect_decisions "
                    "WHERE decision_id = ? OR decision_ref = ? OR effect_id = ? "
                    "OR idempotency_key = ?",
                    (
                        decision.decision_id,
                        decision.checksum,
                        identity_key,
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
                    identity_key,
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
                    identity_key,
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
            fenced = connection.execute(
                "SELECT 1 FROM harness_side_effect_attempt_leases "
                "WHERE effect_id = ? LIMIT 1",
                (side_effect_record_identity_key(outcome),),
            ).fetchone()
            if fenced is not None or outcome.attempt_id is not None:
                raise _store_error(
                    "fenced_side_effect_attempt_required",
                    "fenced side-effect outcome requires complete_attempt",
                    effect_id=outcome.effect_id,
                )
            self._assert_outcome_authorized(connection, outcome)
            existing = self._existing_outcome(connection, outcome)
            if existing is not None:
                return existing
            self._insert_outcome(connection, outcome)
            return outcome

    def complete_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        with self._write("complete Harness side-effect attempt") as connection:
            current = self._assert_current_attempt(connection, attempt)
            self._assert_outcome_authorized(connection, outcome)
            outcome = _bind_outcome_to_attempt(outcome, current)
            existing = self._existing_outcome(connection, outcome)
            if existing is not None:
                return existing
            self._assert_lease_accepts_result(current)
            self._insert_outcome(connection, outcome)
            self._resolve_attempt(
                connection,
                current,
                termination_confirmed=True,
                outcome_ref=outcome.checksum,
            )
            return outcome

    def reconcile_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome:
        if not isinstance(outcome, HarnessSideEffectOutcome):
            raise TypeError("outcome must be HarnessSideEffectOutcome")
        with self._write("reconcile Harness side-effect attempt") as connection:
            current = self._assert_current_attempt(connection, attempt)
            self._assert_outcome_authorized(connection, outcome)
            outcome = _bind_outcome_to_attempt(outcome, current)
            existing = self._existing_outcome(connection, outcome)
            if existing is not None:
                return existing
            if current.status is HarnessSideEffectAttemptStatus.TERMINATED:
                raise _store_error(
                    "stale_side_effect_attempt",
                    "terminated side-effect attempt has no reconciled outcome",
                    effect_id=current.effect_id,
                    attempt_id=current.attempt_id,
                    fencing_generation=current.fencing_generation,
                )
            self._insert_outcome(connection, outcome)
            self._resolve_attempt(
                connection,
                current,
                termination_confirmed=True,
                outcome_ref=outcome.checksum,
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
        outcome = self._outcome_for_effect(
            effect_id,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
            idempotency_key=idempotency_key,
        )
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
        outcome = self._outcome_for_effect(
            effect_id,
            identity_scope_ref=identity_scope_ref,
            subject_scope_ref=subject_scope_ref,
        )
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

    def reserve_attempt(
        self,
        decision: HarnessSideEffectDecision,
    ) -> int:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None

        with self._write("reserve serial Harness side-effect attempt") as connection:
            decision_row = connection.execute(
                "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
                (decision.checksum,),
            ).fetchone()
            if decision_row is None or _decision_from_row(decision_row) != decision:
                raise HarnessValidationError(
                    "handler attempt requires the exact durable authorization"
                )
            fenced = connection.execute(
                "SELECT 1 FROM harness_side_effect_attempt_leases "
                "WHERE effect_id = ? LIMIT 1",
                (side_effect_record_identity_key(decision),),
            ).fetchone()
            if fenced is not None:
                raise _store_error(
                    "fenced_side_effect_attempt_required",
                    "fenced side-effect cannot use serial attempt reservation",
                    effect_id=decision.effect_id,
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
            self._advance_attempt_ledger(
                connection,
                decision=decision,
                current_count=count,
                next_count=next_count,
            )
            return next_count

    def acquire_attempt(
        self,
        decision: HarnessSideEffectDecision,
        *,
        owner_id: str,
        lease_id: str,
    ) -> HarnessSideEffectAttemptLease:
        if not isinstance(decision, HarnessSideEffectDecision):
            raise TypeError("decision must be HarnessSideEffectDecision")
        assert decision.checksum is not None
        owner_id = _lease_identity(owner_id, "owner_id")
        lease_id = _lease_identity(lease_id, "lease_id")

        with self._write("acquire fenced Harness side-effect attempt") as connection:
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
            lease_row = connection.execute(
                "SELECT * FROM harness_side_effect_attempt_leases WHERE lease_id = ?",
                (lease_id,),
            ).fetchone()
            if lease_row is not None:
                existing_lease = _attempt_from_row(lease_row)
                if (
                    existing_lease.owner_id != owner_id
                    or existing_lease.decision_ref != decision.checksum
                ):
                    raise _store_error(
                        "stale_side_effect_attempt",
                        "side-effect lease identity belongs to another owner or decision",
                        effect_id=decision.effect_id,
                        lease_id=lease_id,
                    )
                return existing_lease
            outcome_exists = connection.execute(
                "SELECT 1 FROM harness_side_effect_outcomes WHERE effect_id = ?",
                (side_effect_record_identity_key(decision),),
            ).fetchone()
            if outcome_exists is not None:
                raise _store_error(
                    "side_effect_outcome_already_committed",
                    "side-effect outcome is already committed",
                    effect_id=decision.effect_id,
                )
            current = self._latest_attempt(
                connection,
                side_effect_record_identity_key(decision),
            )
            if (
                current is not None
                and current.status is not HarnessSideEffectAttemptStatus.TERMINATED
            ):
                self._raise_attempt_overlap(current)
            if current is None and count:
                raise _store_error(
                    "side_effect_attempt_termination_unconfirmed",
                    "legacy side-effect attempt has no termination evidence",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    legacy_unfenced=True,
                )
            if count >= limit:
                raise _store_error(
                    "effect_retry_exhausted",
                    "side-effect retry budget is exhausted",
                    effect_id=decision.effect_id,
                    attempt_count=count,
                    attempt_limit=limit,
                )
            next_count = count + 1
            now = self._now()
            lease = HarnessSideEffectAttemptLease.create(
                decision,
                attempt=next_count,
                owner_id=owner_id,
                lease_id=lease_id,
                acquired_at=now,
                lease_expires_at=now + timedelta(seconds=self.attempt_lease_seconds),
            )
            self._advance_attempt_ledger(
                connection,
                decision=decision,
                current_count=count,
                next_count=next_count,
            )
            self._insert_attempt(connection, lease)
            return lease

    def get_attempt(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> HarnessSideEffectAttemptLease | None:
        with self._read("read Harness side-effect attempt") as connection:
            identity_key = self._identity_key_for_effect(
                connection,
                effect_id=effect_id,
                identity_scope_ref=identity_scope_ref,
                subject_scope_ref=subject_scope_ref,
            )
            attempt = (
                None
                if identity_key is None
                else self._latest_attempt(connection, identity_key)
            )
            if attempt is None:
                return None
            if (
                attempt.identity_scope_ref != identity_scope_ref
                or attempt.subject_scope_ref != subject_scope_ref
            ):
                raise HarnessValidationError("side-effect attempt scope mismatch")
            return attempt

    def renew_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectAttemptLease:
        with self._write("renew Harness side-effect attempt") as connection:
            current = self._assert_current_attempt(connection, attempt)
            self._assert_lease_accepts_result(current)
            now = self._now()
            next_expiry = now + timedelta(seconds=self.attempt_lease_seconds)
            if next_expiry <= current.lease_expires_at:
                return current
            renewed = current.renewed(lease_expires_at=next_expiry)
            self._update_attempt(connection, renewed)
            return renewed

    def finish_attempt(
        self,
        attempt: HarnessSideEffectAttemptLease,
        *,
        termination_confirmed: bool,
    ) -> HarnessSideEffectAttemptLease:
        with self._write("finish Harness side-effect attempt") as connection:
            current = self._assert_current_attempt(connection, attempt)
            if current.status is HarnessSideEffectAttemptStatus.TERMINATED:
                if termination_confirmed:
                    return current
                raise HarnessValidationError(
                    "confirmed attempt termination cannot be revoked"
                )
            if (
                current.status is HarnessSideEffectAttemptStatus.INDETERMINATE
                and not termination_confirmed
            ):
                return current
            return self._resolve_attempt(
                connection,
                current,
                termination_confirmed=termination_confirmed,
            )

    def attempt_count(
        self,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> int:
        with self._read("read Harness side-effect attempt count") as connection:
            identity_key = self._identity_key_for_effect(
                connection,
                effect_id=effect_id,
                identity_scope_ref=identity_scope_ref,
                subject_scope_ref=subject_scope_ref,
            )
            if identity_key is None:
                return 0
            row = connection.execute(
                "SELECT * FROM harness_side_effect_attempts WHERE effect_id = ?",
                (identity_key,),
            ).fetchone()
            if row is None:
                raise _corruption("side-effect decision has no attempt ledger")
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
            rows = connection.execute(
                "SELECT * FROM harness_side_effect_outcomes "
                "WHERE json_extract(outcome_json, '$.effect_id') = ? "
                "AND identity_scope_ref = ? AND subject_scope_ref = ?",
                (effect_id, identity_scope_ref, subject_scope_ref),
            ).fetchall()
            if not rows:
                broad_rows = connection.execute(
                    "SELECT * FROM harness_side_effect_outcomes "
                    "WHERE json_extract(outcome_json, '$.effect_id') = ?",
                    (effect_id,),
                ).fetchall()
                if broad_rows:
                    raise HarnessValidationError("side-effect outcome scope mismatch")
                return None
            if len(rows) > 1:
                raise HarnessValidationError(
                    "side-effect identity is ambiguous",
                    code="side_effect_identity_ambiguous",
                )
            row = rows[0]
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
                    side_effect_record_identity_key(outcome),
                    outcome.checksum,
                ),
            )
            if (
                updated.rowcount != 1
            ):  # pragma: no cover - BEGIN IMMEDIATE serializes writers
                raise _store_error(
                    "side_effect_store_conflict",
                    "side-effect disposition update conflicted",
                    effect_id=effect_id,
                )
            attempt_row = connection.execute(
                "SELECT * FROM harness_side_effect_attempt_leases "
                "WHERE outcome_ref = ?",
                (outcome.checksum,),
            ).fetchone()
            if attempt_row is not None:
                attempt = _attempt_from_row(attempt_row)
                self._update_attempt(
                    connection,
                    attempt.relinked_outcome(updated_outcome.checksum),
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
            ledgers: dict[str, sqlite3.Row] = {}
            attempts_by_outcome_ref: dict[
                str,
                list[HarnessSideEffectAttemptLease],
            ] = {}
            for row in connection.execute(
                "SELECT * FROM harness_side_effect_attempts"
            ).fetchall():
                decision = decisions.get(row["decision_ref"])
                if decision is None:
                    raise _corruption("side-effect attempt has no decision")
                _assert_ledger_matches_decision(row, decision)
                ledgers[str(row["effect_id"])] = row
            for row in connection.execute(
                "SELECT * FROM harness_side_effect_attempt_leases"
            ).fetchall():
                attempt = _attempt_from_row(row)
                decision = decisions.get(attempt.decision_ref)
                if decision is None:
                    raise _corruption("side-effect attempt lease has no decision")
                _assert_attempt_matches_decision(attempt, decision)
                ledger = ledgers.get(side_effect_record_identity_key(attempt))
                if ledger is None or attempt.attempt > int(ledger["attempt_count"]):
                    raise _corruption(
                        "side-effect attempt lease exceeds its durable ledger"
                    )
                if attempt.outcome_ref is not None:
                    outcome_row = connection.execute(
                        "SELECT * FROM harness_side_effect_outcomes "
                        "WHERE outcome_ref = ?",
                        (attempt.outcome_ref,),
                    ).fetchone()
                    if outcome_row is None:
                        raise _corruption(
                            "side-effect attempt references a missing outcome"
                        )
                    outcome = _outcome_from_row(outcome_row)
                    if (
                        outcome.effect_id != attempt.effect_id
                        or outcome.decision_ref != attempt.decision_ref
                        or outcome.attempt_id != attempt.attempt_id
                        or outcome.fencing_generation
                        != attempt.fencing_generation
                    ):
                        raise _corruption(
                            "side-effect attempt outcome conflicts with its lease"
                        )
                    attempts_by_outcome_ref.setdefault(
                        attempt.outcome_ref,
                        [],
                    ).append(attempt)
            for row in connection.execute(
                "SELECT * FROM harness_side_effect_outcomes"
            ).fetchall():
                outcome = _outcome_from_row(row)
                decision = decisions.get(outcome.decision_ref)
                if decision is None:
                    raise _corruption("side-effect outcome has no decision")
                _assert_stored_outcome_matches_decision(outcome, decision)
                if outcome.attempt_id is not None:
                    matching_attempts = attempts_by_outcome_ref.get(
                        outcome.checksum,
                        [],
                    )
                    if len(matching_attempts) != 1:
                        raise _corruption(
                            "fenced side-effect outcome must reference one exact "
                            "terminated attempt"
                        )
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

    def _outcome_for_effect(
        self,
        effect_id: str,
        *,
        identity_scope_ref: str | None = None,
        subject_scope_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> HarnessSideEffectOutcome | None:
        with self._read("read Harness side-effect outcome") as connection:
            clauses = ["json_extract(outcome_json, '$.effect_id') = ?"]
            parameters: list[Any] = [effect_id]
            if identity_scope_ref is not None:
                clauses.append("identity_scope_ref = ?")
                parameters.append(identity_scope_ref)
            if subject_scope_ref is not None:
                clauses.append("subject_scope_ref = ?")
                parameters.append(subject_scope_ref)
            if idempotency_key is not None:
                clauses.append("idempotency_key = ?")
                parameters.append(idempotency_key)
            rows = connection.execute(
                "SELECT * FROM harness_side_effect_outcomes WHERE "
                + " AND ".join(clauses),
                tuple(parameters),
            ).fetchall()
            if not rows:
                broad_rows = connection.execute(
                    "SELECT * FROM harness_side_effect_outcomes "
                    "WHERE json_extract(outcome_json, '$.effect_id') = ?",
                    (effect_id,),
                ).fetchall()
                if broad_rows:
                    if idempotency_key is not None and any(
                        row["idempotency_key"] != idempotency_key
                        for row in broad_rows
                    ):
                        raise HarnessValidationError(
                            "side-effect outcome idempotency identity mismatch"
                        )
                    raise HarnessValidationError("side-effect outcome scope mismatch")
                return None
            if len(rows) > 1:
                raise HarnessValidationError(
                    "side-effect identity is ambiguous",
                    code="side_effect_identity_ambiguous",
                )
            outcome = _outcome_from_row(rows[0])
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
    def _identity_key_for_effect(
        connection: sqlite3.Connection,
        *,
        effect_id: str,
        identity_scope_ref: str,
        subject_scope_ref: str,
    ) -> str | None:
        rows = connection.execute(
            "SELECT effect_id FROM harness_side_effect_decisions "
            "WHERE json_extract(decision_json, '$.effect_id') = ? "
            "AND identity_scope_ref = ? AND subject_scope_ref = ?",
            (effect_id, identity_scope_ref, subject_scope_ref),
        ).fetchall()
        keys = {str(row["effect_id"]) for row in rows}
        if len(keys) > 1:
            raise HarnessValidationError(
                "side-effect identity is ambiguous",
                code="side_effect_identity_ambiguous",
            )
        if keys:
            return next(iter(keys))
        broad_rows = connection.execute(
            "SELECT 1 FROM harness_side_effect_decisions "
            "WHERE json_extract(decision_json, '$.effect_id') = ?",
            (effect_id,),
        ).fetchall()
        if broad_rows:
            raise HarnessValidationError("side-effect attempt scope mismatch")
        return None

    @staticmethod
    def _assert_attempt_ledger(
        connection: sqlite3.Connection,
        decision: HarnessSideEffectDecision,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM harness_side_effect_attempts WHERE effect_id = ?",
            (side_effect_record_identity_key(decision),),
        ).fetchone()
        if row is None:
            raise _corruption("side-effect decision has no attempt ledger")
        _assert_ledger_matches_decision(row, decision)
        return row

    @staticmethod
    def _advance_attempt_ledger(
        connection: sqlite3.Connection,
        *,
        decision: HarnessSideEffectDecision,
        current_count: int,
        next_count: int,
    ) -> None:
        updated = connection.execute(
            "UPDATE harness_side_effect_attempts SET attempt_count = ? "
            "WHERE effect_id = ? AND decision_ref = ? AND attempt_count = ?",
            (
                next_count,
                side_effect_record_identity_key(decision),
                decision.checksum,
                current_count,
            ),
        )
        if (
            updated.rowcount != 1
        ):  # pragma: no cover - BEGIN IMMEDIATE serializes writers
            raise _store_error(
                "side_effect_store_conflict",
                "side-effect attempt reservation conflicted",
                effect_id=decision.effect_id,
            )

    @staticmethod
    def _assert_outcome_authorized(
        connection: sqlite3.Connection,
        outcome: HarnessSideEffectOutcome,
    ) -> None:
        decision_row = connection.execute(
            "SELECT * FROM harness_side_effect_decisions WHERE decision_ref = ?",
            (outcome.decision_ref,),
        ).fetchone()
        if decision_row is None:
            raise HarnessValidationError(
                "side-effect outcome has no durable authorization"
            )
        _assert_outcome_matches_decision(outcome, _decision_from_row(decision_row))

    @staticmethod
    def _existing_outcome(
        connection: sqlite3.Connection,
        outcome: HarnessSideEffectOutcome,
    ) -> HarnessSideEffectOutcome | None:
        assert outcome.checksum is not None
        rows = _unique_rows(
            connection.execute(
                "SELECT * FROM harness_side_effect_outcomes "
                "WHERE outcome_ref = ? OR outcome_id = ? OR effect_id = ? "
                "OR idempotency_key = ?",
                (
                    outcome.checksum,
                    outcome.outcome_id,
                    side_effect_record_identity_key(outcome),
                    outcome.idempotency_key,
                ),
            ).fetchall(),
            key="outcome_ref",
        )
        if not rows:
            return None
        existing = tuple(_outcome_from_row(row) for row in rows)
        if any(candidate != outcome for candidate in existing):
            raise HarnessValidationError("side-effect outcome identity is immutable")
        return existing[0]

    @staticmethod
    def _insert_outcome(
        connection: sqlite3.Connection,
        outcome: HarnessSideEffectOutcome,
    ) -> None:
        assert outcome.checksum is not None
        connection.execute(
            "INSERT INTO harness_side_effect_outcomes ("
                "outcome_ref, outcome_id, effect_id, decision_ref, run_id, "
            "identity_scope_ref, subject_scope_ref, idempotency_key, "
            "disposition, outcome_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                outcome.checksum,
                outcome.outcome_id,
                side_effect_record_identity_key(outcome),
                outcome.decision_ref,
                outcome.run_id,
                outcome.identity_scope_ref,
                outcome.subject_scope_ref,
                outcome.idempotency_key,
                outcome.disposition.value,
                stable_json_dumps(outcome.to_dict()),
            ),
        )

    @staticmethod
    def _latest_attempt(
        connection: sqlite3.Connection,
        identity_key: str,
    ) -> HarnessSideEffectAttemptLease | None:
        row = connection.execute(
            "SELECT * FROM harness_side_effect_attempt_leases "
            "WHERE effect_id = ? ORDER BY fencing_generation DESC LIMIT 1",
            (identity_key,),
        ).fetchone()
        return None if row is None else _attempt_from_row(row)

    def _assert_current_attempt(
        self,
        connection: sqlite3.Connection,
        attempt: HarnessSideEffectAttemptLease,
    ) -> HarnessSideEffectAttemptLease:
        if not isinstance(attempt, HarnessSideEffectAttemptLease):
            raise TypeError("attempt must be HarnessSideEffectAttemptLease")
        current = self._latest_attempt(
            connection,
            side_effect_record_identity_key(attempt),
        )
        if current is None or not _same_attempt_generation(current, attempt):
            raise _store_error(
                "stale_side_effect_attempt",
                "side-effect attempt no longer owns the current fence",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )
        return current

    def _assert_lease_accepts_result(
        self,
        attempt: HarnessSideEffectAttemptLease,
    ) -> None:
        if attempt.status is not HarnessSideEffectAttemptStatus.ACTIVE:
            raise _store_error(
                "stale_side_effect_attempt",
                "side-effect attempt is no longer active",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )
        if self._now() >= attempt.lease_expires_at:
            raise _store_error(
                "side_effect_attempt_lease_expired",
                "side-effect attempt lease expired before the operation",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )

    def _raise_attempt_overlap(self, attempt: HarnessSideEffectAttemptLease) -> None:
        now = self._now()
        code = (
            "side_effect_attempt_in_progress"
            if attempt.status is HarnessSideEffectAttemptStatus.ACTIVE
            and now < attempt.lease_expires_at
            else "side_effect_attempt_termination_unconfirmed"
        )
        raise _store_error(
            code,
            "side-effect attempt cannot overlap an unconfirmed predecessor",
            effect_id=attempt.effect_id,
            attempt_id=attempt.attempt_id,
            fencing_generation=attempt.fencing_generation,
            lease_expired=now >= attempt.lease_expires_at,
        )

    @staticmethod
    def _insert_attempt(
        connection: sqlite3.Connection,
        attempt: HarnessSideEffectAttemptLease,
    ) -> None:
        connection.execute(
            "INSERT INTO harness_side_effect_attempt_leases ("
            "attempt_id, lease_id, owner_id, effect_id, decision_ref, idempotency_key, "
            "identity_scope_ref, subject_scope_ref, attempt, fencing_generation, "
            "acquired_at, lease_expires_at, status, termination_confirmed, "
            "resolved_at, outcome_ref, attempt_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _attempt_row_values(attempt),
        )

    @staticmethod
    def _update_attempt(
        connection: sqlite3.Connection,
        attempt: HarnessSideEffectAttemptLease,
    ) -> None:
        updated = connection.execute(
            "UPDATE harness_side_effect_attempt_leases SET "
            "lease_expires_at = ?, status = ?, termination_confirmed = ?, "
            "resolved_at = ?, outcome_ref = ?, attempt_json = ? "
                "WHERE attempt_id = ? AND lease_id = ? AND effect_id = ? "
            "AND fencing_generation = ?",
            (
                format_datetime(attempt.lease_expires_at),
                attempt.status.value,
                int(attempt.termination_confirmed),
                format_datetime(attempt.resolved_at),
                attempt.outcome_ref,
                stable_json_dumps(attempt.to_dict()),
                attempt.attempt_id,
                attempt.lease_id,
                side_effect_record_identity_key(attempt),
                attempt.fencing_generation,
            ),
        )
        if updated.rowcount != 1:
            raise _store_error(
                "stale_side_effect_attempt",
                "side-effect attempt update lost its current fence",
                effect_id=attempt.effect_id,
                attempt_id=attempt.attempt_id,
                fencing_generation=attempt.fencing_generation,
            )

    def _resolve_attempt(
        self,
        connection: sqlite3.Connection,
        attempt: HarnessSideEffectAttemptLease,
        *,
        termination_confirmed: bool,
        outcome_ref: str | None = None,
    ) -> HarnessSideEffectAttemptLease:
        resolved = attempt.resolved(
            termination_confirmed=termination_confirmed,
            resolved_at=self._now(),
            outcome_ref=outcome_ref,
        )
        self._update_attempt(connection, resolved)
        return resolved

    def _now(self) -> datetime:
        return self._clock()

    def _initialize_schema(self) -> None:
        try:
            with self._connection() as connection:
                _require_supported_schema_version(
                    _stored_schema_version(connection),
                )
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                )
                if journal_mode.lower() != "wal":
                    raise _store_error(
                        "side_effect_store_unavailable",
                        "SQLite Harness side-effect store requires WAL mode",
                        journal_mode=journal_mode,
                    )
                schema_version = _stored_schema_version(connection)
                legacy_identity_migration = schema_version in (1, 2)
                if legacy_identity_migration:
                    connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    schema_version = _stored_schema_version(connection)
                    _require_supported_schema_version(schema_version)
                    _execute_schema(connection)
                    if legacy_identity_migration:
                        _migrate_identity_keys(connection)
                    if schema_version is None:
                        connection.execute(
                            "INSERT INTO harness_side_effect_store_metadata "
                            "(schema_version, created_at) "
                            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                            (SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION,),
                        )
                    elif schema_version in (1, 2):
                        updated = connection.execute(
                            "UPDATE harness_side_effect_store_metadata "
                            "SET schema_version = ? WHERE schema_version IN (1, 2)",
                            (SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION,),
                        )
                        if updated.rowcount != 1:
                            raise _corruption(
                                "SQLite Harness side-effect schema migration lost "
                                "its version fence"
                            )
                    connection.commit()
                except BaseException:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
                finally:
                    if legacy_identity_migration:
                        connection.execute("PRAGMA foreign_keys=ON")
        except HarnessValidationError:
            raise
        except sqlite3.Error as exc:
            raise _sqlite_error(
                exc, operation="initialize Harness side-effect store"
            ) from exc
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
            raise _sqlite_error(
                exc, operation="open Harness side-effect store"
            ) from exc

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
        "effect_id": side_effect_record_identity_key(decision),
        "run_id": decision.run_id,
        "origin": decision.origin.value,
        "command_ordinal": decision.command_ordinal,
        "identity_scope_ref": decision.identity_scope_ref,
        "subject_scope_ref": decision.subject_scope_ref,
        "idempotency_key": decision.idempotency_key,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise _corruption(
            "stored side-effect decision indexes do not match its payload"
        )
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
        "effect_id": side_effect_record_identity_key(outcome),
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


def _attempt_from_row(row: sqlite3.Row) -> HarnessSideEffectAttemptLease:
    try:
        payload = json_loads(str(row["attempt_json"]))
        attempt = HarnessSideEffectAttemptLease.from_dict(payload)
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise _corruption("stored side-effect attempt lease is invalid") from exc
    expected = {
        "attempt_id": attempt.attempt_id,
        "lease_id": attempt.lease_id,
        "owner_id": attempt.owner_id,
        "effect_id": side_effect_record_identity_key(attempt),
        "decision_ref": attempt.decision_ref,
        "idempotency_key": attempt.idempotency_key,
        "identity_scope_ref": attempt.identity_scope_ref,
        "subject_scope_ref": attempt.subject_scope_ref,
        "attempt": attempt.attempt,
        "fencing_generation": attempt.fencing_generation,
        "acquired_at": format_datetime(attempt.acquired_at),
        "lease_expires_at": format_datetime(attempt.lease_expires_at),
        "status": attempt.status.value,
        "termination_confirmed": int(attempt.termination_confirmed),
        "resolved_at": format_datetime(attempt.resolved_at),
        "outcome_ref": attempt.outcome_ref,
    }
    if any(row[key] != value for key, value in expected.items()):
        raise _corruption("stored side-effect attempt indexes do not match its payload")
    return attempt


def _attempt_row_values(attempt: HarnessSideEffectAttemptLease) -> tuple[Any, ...]:
    return (
        attempt.attempt_id,
        attempt.lease_id,
        attempt.owner_id,
        side_effect_record_identity_key(attempt),
        attempt.decision_ref,
        attempt.idempotency_key,
        attempt.identity_scope_ref,
        attempt.subject_scope_ref,
        attempt.attempt,
        attempt.fencing_generation,
        format_datetime(attempt.acquired_at),
        format_datetime(attempt.lease_expires_at),
        attempt.status.value,
        int(attempt.termination_confirmed),
        format_datetime(attempt.resolved_at),
        attempt.outcome_ref,
        stable_json_dumps(attempt.to_dict()),
    )


def _assert_ledger_matches_decision(
    row: sqlite3.Row,
    decision: HarnessSideEffectDecision,
) -> None:
    expected = {
        "effect_id": side_effect_record_identity_key(decision),
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


def _assert_attempt_matches_decision(
    attempt: HarnessSideEffectAttemptLease,
    decision: HarnessSideEffectDecision,
) -> None:
    if (
        attempt.effect_id != decision.effect_id
        or attempt.run_id != decision.run_id
        or attempt.origin != decision.origin
        or attempt.graph_id != decision.graph_id
        or attempt.graph_version != decision.graph_version
        or attempt.graph_ref != decision.graph_ref
        or attempt.graph_checksum != decision.graph_checksum
        or attempt.node_id != decision.node_id
        or attempt.node_instance_id != decision.node_instance_id
        or attempt.activity_id != decision.activity_id
        or attempt.terminal_action != decision.terminal_action
        or attempt.activity_attempt != decision.attempt
        or attempt.decision_ref != decision.checksum
        or attempt.idempotency_key != decision.idempotency_key
        or attempt.identity_scope_ref != decision.identity_scope_ref
        or attempt.subject_scope_ref != decision.subject_scope_ref
    ):
        raise _corruption("side-effect attempt lease conflicts with its decision")


def _bind_outcome_to_attempt(
    outcome: HarnessSideEffectOutcome,
    attempt: HarnessSideEffectAttemptLease,
) -> HarnessSideEffectOutcome:
    if (
        outcome.effect_id != attempt.effect_id
        or outcome.run_id != attempt.run_id
        or outcome.origin != attempt.origin
        or outcome.graph_id != attempt.graph_id
        or outcome.graph_version != attempt.graph_version
        or outcome.graph_ref != attempt.graph_ref
        or outcome.graph_checksum != attempt.graph_checksum
        or outcome.node_id != attempt.node_id
        or outcome.node_instance_id != attempt.node_instance_id
        or outcome.activity_id != attempt.activity_id
        or outcome.terminal_action != attempt.terminal_action
        or outcome.attempt != attempt.activity_attempt
        or outcome.decision_ref != attempt.decision_ref
        or outcome.idempotency_key != attempt.idempotency_key
        or outcome.identity_scope_ref != attempt.identity_scope_ref
        or outcome.subject_scope_ref != attempt.subject_scope_ref
    ):
        raise HarnessValidationError(
            "side-effect outcome attempt identity mismatch",
            code="side_effect_outcome_attempt_identity_mismatch",
        )
    if outcome.attempt_id is None:
        return replace(
            outcome,
            attempt_id=attempt.attempt_id,
            fencing_generation=attempt.fencing_generation,
            schema_version="newsroom.harness-side-effect-outcome/v3",
            checksum=None,
        )
    if (
        outcome.attempt_id != attempt.attempt_id
        or outcome.fencing_generation != attempt.fencing_generation
    ):
        raise _store_error(
            "stale_side_effect_attempt",
            "side-effect outcome carries a stale fencing identity",
            effect_id=outcome.effect_id,
            attempt_id=outcome.attempt_id,
            fencing_generation=outcome.fencing_generation,
        )
    return outcome


def _same_attempt_generation(
    left: HarnessSideEffectAttemptLease,
    right: HarnessSideEffectAttemptLease,
) -> bool:
    return (
        left.attempt_id == right.attempt_id
        and left.lease_id == right.lease_id
        and left.owner_id == right.owner_id
        and left.effect_id == right.effect_id
        and left.run_id == right.run_id
        and left.origin == right.origin
        and left.graph_id == right.graph_id
        and left.graph_version == right.graph_version
        and left.graph_ref == right.graph_ref
        and left.graph_checksum == right.graph_checksum
        and left.node_id == right.node_id
        and left.node_instance_id == right.node_instance_id
        and left.activity_id == right.activity_id
        and left.terminal_action == right.terminal_action
        and left.decision_ref == right.decision_ref
        and left.idempotency_key == right.idempotency_key
        and left.identity_scope_ref == right.identity_scope_ref
        and left.subject_scope_ref == right.subject_scope_ref
        and left.attempt == right.attempt
        and left.activity_attempt == right.activity_attempt
        and left.fencing_generation == right.fencing_generation
    )


def _assert_outcome_matches_decision(
    outcome: HarnessSideEffectOutcome,
    decision: HarnessSideEffectDecision,
) -> None:
    if (
        outcome.decision_ref != decision.checksum
        or outcome.effect_id != decision.effect_id
        or outcome.run_id != decision.run_id
        or outcome.graph_id != decision.graph_id
        or outcome.graph_version != decision.graph_version
        or outcome.graph_ref != decision.graph_ref
        or outcome.graph_checksum != decision.graph_checksum
        or outcome.origin != decision.origin
        or outcome.node_id != decision.node_id
        or outcome.node_instance_id != decision.node_instance_id
        or outcome.activity_id != decision.activity_id
        or outcome.attempt != decision.attempt
        or outcome.terminal_action != decision.terminal_action
        or outcome.kind != decision.kind
        or outcome.handler != decision.handler
        or outcome.idempotency_key != decision.idempotency_key
        or outcome.identity_scope_ref != decision.identity_scope_ref
        or outcome.subject_scope_ref != decision.subject_scope_ref
        or outcome.atomic_group != decision.atomic_group
    ):
        raise HarnessValidationError("side-effect outcome does not match authorization")


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


def _lease_identity(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HarnessValidationError(
            f"{field_name} is required and must not contain surrounding whitespace"
        )
    return value


def _stored_schema_version(connection: sqlite3.Connection) -> int | None:
    metadata_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'harness_side_effect_store_metadata'"
    ).fetchone()
    if metadata_table is None:
        existing_objects = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        if existing_objects:
            raise _corruption(
                "SQLite Harness side-effect metadata is missing from a "
                "non-empty database"
            )
        return None
    rows = connection.execute(
        "SELECT schema_version FROM harness_side_effect_store_metadata"
    ).fetchall()
    if len(rows) != 1:
        raise _corruption(
            "SQLite Harness side-effect metadata must contain exactly one version"
        )
    value = rows[0]["schema_version"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _corruption("SQLite Harness side-effect schema version is invalid")
    return value


def _migrate_identity_keys(connection: sqlite3.Connection) -> None:
    """Upgrade effect-only SQLite indexes to complete Graph identity keys."""
    decisions = connection.execute(
        "SELECT decision_ref, effect_id, decision_json "
        "FROM harness_side_effect_decisions"
    ).fetchall()
    decision_keys: dict[str, str] = {}
    decision_payloads: dict[str, dict[str, Any]] = {}
    for row in decisions:
        try:
            payload = json_loads(str(row["decision_json"]))
            decision = HarnessSideEffectDecision.from_dict(payload)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise _corruption("legacy side-effect decision is invalid") from exc
        assert decision.checksum == row["decision_ref"]
        key = side_effect_record_identity_key(decision)
        decision_keys[str(row["decision_ref"])] = key
        decision_payloads[str(row["decision_ref"])] = payload

    for decision_ref, key in decision_keys.items():
        connection.execute(
            "UPDATE harness_side_effect_decisions SET effect_id = ? "
            "WHERE decision_ref = ?",
            (key, decision_ref),
        )

    connection.execute(
        "UPDATE harness_side_effect_attempts SET effect_id = "
        "(SELECT effect_id FROM harness_side_effect_decisions d "
        " WHERE d.decision_ref = harness_side_effect_attempts.decision_ref)"
    )
    connection.execute(
        "UPDATE harness_side_effect_attempt_leases SET effect_id = "
        "(SELECT effect_id FROM harness_side_effect_decisions d "
        " WHERE d.decision_ref = harness_side_effect_attempt_leases.decision_ref)"
    )
    outcomes = connection.execute(
        "SELECT outcome_ref, outcome_json, decision_ref "
        "FROM harness_side_effect_outcomes"
    ).fetchall()
    for row in outcomes:
        try:
            payload = json_loads(str(row["outcome_json"]))
            outcome = HarnessSideEffectOutcome.from_dict(payload)
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise _corruption("legacy side-effect outcome is invalid") from exc
        key = decision_keys.get(str(row["decision_ref"]))
        if key is None:
            raise _corruption("legacy side-effect outcome has no decision")
        connection.execute(
            "UPDATE harness_side_effect_outcomes SET effect_id = ? "
            "WHERE outcome_ref = ?",
            (key, row["outcome_ref"]),
        )

    leases = connection.execute(
        "SELECT attempt_id, attempt_json, decision_ref "
        "FROM harness_side_effect_attempt_leases"
    ).fetchall()
    for row in leases:
        try:
            payload = json_loads(str(row["attempt_json"]))
        except (TypeError, ValueError) as exc:
            raise _corruption("legacy side-effect attempt lease is invalid") from exc
        decision_payload = decision_payloads.get(str(row["decision_ref"]))
        if decision_payload is None:
            raise _corruption("legacy side-effect attempt lease has no decision")
        payload.setdefault("run_id", decision_payload.get("run_id"))
        payload.setdefault("origin", decision_payload.get("origin"))
        payload.setdefault("terminal_action", decision_payload.get("terminal_action"))
        payload.setdefault("activity_attempt", decision_payload.get("attempt"))
        connection.execute(
            "UPDATE harness_side_effect_attempt_leases SET attempt_json = ? "
            "WHERE attempt_id = ?",
            (stable_json_dumps(payload), row["attempt_id"]),
        )


def _require_supported_schema_version(schema_version: int | None) -> None:
    if schema_version not in (None, 1, 2, SQLITE_HARNESS_SIDE_EFFECT_SCHEMA_VERSION):
        raise _store_error(
            "side_effect_store_schema_unsupported",
            "SQLite Harness side-effect schema version is unsupported",
            schema_version=schema_version,
        )


def _execute_schema(connection: sqlite3.Connection) -> None:
    pending: list[str] = []
    for line in _SCHEMA.splitlines(keepends=True):
        pending.append(line)
        statement = "".join(pending)
        if not sqlite3.complete_statement(statement):
            continue
        if statement.strip():
            connection.execute(statement)
        pending.clear()
    if "".join(pending).strip():  # pragma: no cover - static schema invariant
        raise RuntimeError("SQLite Harness side-effect schema is incomplete")


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
