from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Iterator

from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.node_output import (
    HarnessAdmittedGraphActivityAttempt,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputCommitGuard,
    HarnessNodeOutputLease,
    HarnessNodeOutputResourceIdentity,
    HarnessNodeOutputResourcePort,
    HarnessNodeOutputStagedWrite,
    HarnessNodeOutputStaleOwnerError,
)
from framework.harness.control_plane.errors import HarnessValidationError


class SQLiteHarnessNodeOutputResource:
    """Durable, fenced node-output resource backed by SQLite transactions."""

    def __init__(self, path: str | Path) -> None:
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(database_path)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def acquire_after_admission(
        self,
        activity: HarnessGraphActivity,
        admission: HarnessAdmittedGraphActivityAttempt,
    ) -> HarnessNodeOutputLease:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        if not isinstance(admission, HarnessAdmittedGraphActivityAttempt):
            raise TypeError("admission must be HarnessAdmittedGraphActivityAttempt")
        mismatches = tuple(
            field
            for field, expected, actual in (
                ("activity_id", activity.activity_id, admission.activity_id),
                ("activity_checksum", activity.activity_checksum, admission.activity_checksum),
                ("idempotency_key", activity.idempotency_key, admission.idempotency_key),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "admitted attempt does not match its Graph activity",
                code="graph_node_output_admission_mismatch",
                details={"mismatches": list(mismatches)},
            )
        resource = HarnessNodeOutputResourceIdentity.for_activity(activity)
        with self._transaction() as db:
            state = db.execute(
                "SELECT generation, current_lease_ref, committed_json FROM resource_state WHERE resource_ref = ?",
                (resource.resource_ref,),
            ).fetchone()
            if state is not None and state["committed_json"] is not None:
                existing = HarnessNodeOutputCommit.from_dict(
                    json.loads(state["committed_json"])
                )
                if existing.activity_id == activity.activity_id:
                    raise HarnessValidationError(
                        "node-output resource is already committed",
                        code="graph_node_output_already_committed",
                        details={"resource_ref": resource.resource_ref},
                    )
                # A distinct Graph activity id is a controller-authorized
                # retry. Clear only the current resource slot; the prior
                # candidate remains in the durable event/result history.
                db.execute(
                    "UPDATE resource_state SET committed_json = NULL WHERE resource_ref = ?",
                    (resource.resource_ref,),
                )
            prior = db.execute(
                "SELECT lease_json FROM leases WHERE admission_ref = ?",
                (admission.admission_ref,),
            ).fetchone()
            current = self._lease_row(db, state["current_lease_ref"] if state else None)
            if prior is not None:
                lease = HarnessNodeOutputLease.from_dict(json.loads(prior["lease_json"]))
                if current == lease:
                    return lease
                raise HarnessNodeOutputStaleOwnerError(
                    resource_ref=resource.resource_ref,
                    owner_attempt_id=lease.owner_attempt_id,
                    generation=lease.generation,
                )
            owner = db.execute(
                "SELECT lease_json FROM leases WHERE resource_ref = ? AND owner_attempt_id = ?",
                (resource.resource_ref, admission.owner_attempt_id),
            ).fetchone()
            if owner is not None:
                lease = HarnessNodeOutputLease.from_dict(json.loads(owner["lease_json"]))
                if lease.admission_ref != admission.admission_ref:
                    raise HarnessValidationError(
                        "node-output owner attempt identity is immutable",
                        code="graph_node_output_owner_identity_conflict",
                    )
                if current == lease:
                    return lease
                raise HarnessNodeOutputStaleOwnerError(
                    resource_ref=resource.resource_ref,
                    owner_attempt_id=lease.owner_attempt_id,
                    generation=lease.generation,
                )
            generation = (int(state["generation"]) if state else 0) + 1
            lease = HarnessNodeOutputLease(
                resource=resource,
                activity_id=activity.activity_id,
                activity_checksum=activity.activity_checksum,
                admission_ref=admission.admission_ref,
                owner_attempt_id=admission.owner_attempt_id,
                generation=generation,
                acquired_at=admission.admitted_at,
                previous_lease_ref=current.lease_ref if current else None,
            )
            if current is not None:
                db.execute("DELETE FROM staged WHERE lease_ref = ?", (current.lease_ref,))
            db.execute(
                "INSERT INTO leases(admission_ref, resource_ref, owner_attempt_id, lease_json) VALUES (?, ?, ?, ?)",
                (lease.admission_ref, resource.resource_ref, lease.owner_attempt_id, _dump(lease.to_dict())),
            )
            db.execute(
                "INSERT INTO resource_state(resource_ref, generation, current_lease_ref, committed_json) VALUES (?, ?, ?, NULL) "
                "ON CONFLICT(resource_ref) DO UPDATE SET generation=excluded.generation, current_lease_ref=excluded.current_lease_ref",
                (resource.resource_ref, generation, lease.lease_ref),
            )
            return lease

    def stage(self, lease: HarnessNodeOutputLease, candidate: HarnessNodeOutputCandidate, *, staged_at: datetime) -> HarnessNodeOutputStagedWrite:
        if not isinstance(lease, HarnessNodeOutputLease):
            raise TypeError("lease must be HarnessNodeOutputLease")
        if not isinstance(candidate, HarnessNodeOutputCandidate):
            raise TypeError("candidate must be HarnessNodeOutputCandidate")
        with self._transaction() as db:
            self._assert_current(db, lease)
            row = db.execute("SELECT stage_json FROM staged WHERE lease_ref = ?", (lease.lease_ref,)).fetchone()
            if row is not None:
                existing = HarnessNodeOutputStagedWrite.from_dict(json.loads(row["stage_json"]))
                if existing.candidate != candidate:
                    raise HarnessValidationError("node-output lease cannot stage conflicting candidates", code="graph_node_output_stage_conflict")
                return existing
            staged = HarnessNodeOutputStagedWrite(
                lease_ref=lease.lease_ref, resource_ref=lease.resource.resource_ref,
                activity_id=lease.activity_id, owner_attempt_id=lease.owner_attempt_id,
                generation=lease.generation, candidate=candidate, staged_at=staged_at,
            )
            db.execute("INSERT INTO staged(stage_ref, resource_ref, lease_ref, stage_json) VALUES (?, ?, ?, ?)", (staged.stage_ref, staged.resource_ref, staged.lease_ref, _dump(staged.to_dict())))
            return staged

    def commit(self, staged: HarnessNodeOutputStagedWrite, guard: HarnessNodeOutputCommitGuard, *, committed_at: datetime) -> HarnessNodeOutputCommit:
        if not isinstance(staged, HarnessNodeOutputStagedWrite):
            raise TypeError("staged must be HarnessNodeOutputStagedWrite")
        if not isinstance(guard, HarnessNodeOutputCommitGuard):
            raise TypeError("guard must be HarnessNodeOutputCommitGuard")
        with self._transaction() as db:
            current = self._current_lease(db, staged.resource_ref)
            if current is None or (current.lease_ref, current.owner_attempt_id, current.generation) != (staged.lease_ref, staged.owner_attempt_id, staged.generation):
                raise HarnessNodeOutputStaleOwnerError(resource_ref=staged.resource_ref, owner_attempt_id=staged.owner_attempt_id, generation=staged.generation)
            state = db.execute("SELECT committed_json FROM resource_state WHERE resource_ref = ?", (staged.resource_ref,)).fetchone()
            existing = None if state is None or state["committed_json"] is None else HarnessNodeOutputCommit.from_dict(json.loads(state["committed_json"]))
            if existing is not None:
                if existing.stage_ref != staged.stage_ref:
                    raise HarnessValidationError("node-output resource cannot commit conflicting candidates", code="graph_node_output_commit_conflict")
                return existing
            row = db.execute("SELECT stage_json FROM staged WHERE stage_ref = ?", (staged.stage_ref,)).fetchone()
            if row is None or HarnessNodeOutputStagedWrite.from_dict(json.loads(row["stage_json"])) != staged:
                raise HarnessValidationError("node-output staged write is not owned by this resource", code="graph_node_output_stage_missing")
            guard.assert_allows_normal_output()
            commit = HarnessNodeOutputCommit(stage_ref=staged.stage_ref, lease_ref=staged.lease_ref, resource_ref=staged.resource_ref, activity_id=staged.activity_id, owner_attempt_id=staged.owner_attempt_id, generation=staged.generation, candidate=staged.candidate, committed_at=committed_at)
            db.execute("UPDATE resource_state SET committed_json = ? WHERE resource_ref = ?", (_dump(commit.to_dict()), staged.resource_ref))
            return commit

    def discard(self, staged: HarnessNodeOutputStagedWrite) -> bool:
        if not isinstance(staged, HarnessNodeOutputStagedWrite):
            raise TypeError("staged must be HarnessNodeOutputStagedWrite")
        with self._transaction() as db:
            state = db.execute("SELECT committed_json FROM resource_state WHERE resource_ref = ?", (staged.resource_ref,)).fetchone()
            if state is not None and state["committed_json"] is not None:
                return False
            row = db.execute("SELECT stage_json FROM staged WHERE stage_ref = ?", (staged.stage_ref,)).fetchone()
            if row is None or HarnessNodeOutputStagedWrite.from_dict(json.loads(row["stage_json"])) != staged:
                return False
            db.execute("DELETE FROM staged WHERE stage_ref = ?", (staged.stage_ref,))
            return True

    def revoke(self, lease: HarnessNodeOutputLease) -> bool:
        if not isinstance(lease, HarnessNodeOutputLease):
            raise TypeError("lease must be HarnessNodeOutputLease")
        with self._transaction() as db:
            state = db.execute("SELECT committed_json, current_lease_ref FROM resource_state WHERE resource_ref = ?", (lease.resource.resource_ref,)).fetchone()
            if state is None or state["committed_json"] is not None or state["current_lease_ref"] != lease.lease_ref:
                return False
            db.execute("UPDATE resource_state SET current_lease_ref = NULL WHERE resource_ref = ?", (lease.resource.resource_ref,))
            db.execute("DELETE FROM staged WHERE lease_ref = ?", (lease.lease_ref,))
            return True

    def current_lease(self, resource: HarnessNodeOutputResourceIdentity) -> HarnessNodeOutputLease | None:
        if not isinstance(resource, HarnessNodeOutputResourceIdentity):
            raise TypeError("resource must be HarnessNodeOutputResourceIdentity")
        with self._transaction() as db:
            state = db.execute("SELECT current_lease_ref FROM resource_state WHERE resource_ref = ?", (resource.resource_ref,)).fetchone()
            return self._current_lease(db, resource.resource_ref) if state and state["current_lease_ref"] else None

    def committed_output(self, resource: HarnessNodeOutputResourceIdentity) -> HarnessNodeOutputCommit | None:
        if not isinstance(resource, HarnessNodeOutputResourceIdentity):
            raise TypeError("resource must be HarnessNodeOutputResourceIdentity")
        with self._transaction() as db:
            row = db.execute("SELECT committed_json FROM resource_state WHERE resource_ref = ?", (resource.resource_ref,)).fetchone()
            return None if row is None or row["committed_json"] is None else HarnessNodeOutputCommit.from_dict(json.loads(row["committed_json"]))

    def _initialize(self) -> None:
        self._connection.executescript("""
        CREATE TABLE IF NOT EXISTS resource_state(resource_ref TEXT PRIMARY KEY, generation INTEGER NOT NULL, current_lease_ref TEXT, committed_json TEXT);
        CREATE TABLE IF NOT EXISTS leases(admission_ref TEXT PRIMARY KEY, resource_ref TEXT NOT NULL, owner_attempt_id TEXT NOT NULL, lease_json TEXT NOT NULL, UNIQUE(resource_ref, owner_attempt_id));
        CREATE TABLE IF NOT EXISTS staged(stage_ref TEXT PRIMARY KEY, resource_ref TEXT NOT NULL, lease_ref TEXT NOT NULL, stage_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS leases_resource_idx ON leases(resource_ref);
        CREATE INDEX IF NOT EXISTS staged_lease_idx ON staged(lease_ref);
        """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _lease_row(self, db: sqlite3.Connection, lease_ref: str | None) -> HarnessNodeOutputLease | None:
        if not lease_ref:
            return None
        rows = db.execute("SELECT lease_json FROM leases").fetchall()
        for row in rows:
            lease = HarnessNodeOutputLease.from_dict(json.loads(row["lease_json"]))
            if lease.lease_ref == lease_ref:
                return lease
        return None

    def _current_lease(self, db: sqlite3.Connection, resource_ref: str | None) -> HarnessNodeOutputLease | None:
        if not resource_ref:
            return None
        row = db.execute("SELECT current_lease_ref FROM resource_state WHERE resource_ref = ?", (resource_ref,)).fetchone()
        if row is None or row["current_lease_ref"] is None:
            return None
        rows = db.execute("SELECT lease_json FROM leases WHERE resource_ref = ?", (resource_ref,)).fetchall()
        for candidate in rows:
            parsed = HarnessNodeOutputLease.from_dict(json.loads(candidate["lease_json"]))
            if parsed.lease_ref == row["current_lease_ref"]:
                return parsed
        return None

    def _assert_current(self, db: sqlite3.Connection, lease: HarnessNodeOutputLease) -> None:
        current = self._current_lease(db, lease.resource.resource_ref)
        if current != lease:
            raise HarnessNodeOutputStaleOwnerError(resource_ref=lease.resource.resource_ref, owner_attempt_id=lease.owner_attempt_id, generation=lease.generation)


def _dump(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = ["SQLiteHarnessNodeOutputResource"]
