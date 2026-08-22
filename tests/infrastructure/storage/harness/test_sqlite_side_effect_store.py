from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOutcome,
    HarnessSideEffectReaderPort,
    HarnessSideEffectStorePort,
    HarnessValidationError,
)
from framework.harness.side_effects.models import HarnessSideEffectAttemptStatus
from framework.harness.side_effects.ports import HarnessFencedSideEffectStorePort
from framework.shared.json import json_loads, stable_json_dumps
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore


IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "tenant-1"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})
COMMITTED_AT = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)
GRAPH_ID = "test.graph"
GRAPH_VERSION = "1"
GRAPH_REF = f"{GRAPH_ID}@{GRAPH_VERSION}"
GRAPH_CHECKSUM = checksum_for({"graph_id": GRAPH_ID, "graph_version": GRAPH_VERSION})


def _store(tmp_path: Path, **kwargs) -> SQLiteHarnessSideEffectStore:
    return SQLiteHarnessSideEffectStore(
        tmp_path / "harness-side-effects.sqlite3",
        **kwargs,
    )


class _MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _intent(
    *,
    effect_id: str = "effect-worker-1",
    origin: str = "worker",
    node_instance_id: str | None = None,
) -> HarnessSideEffectIntent:
    common = {
        "effect_id": effect_id,
        "kind": "artifact",
        "run_id": "run-1",
        "graph_id": GRAPH_ID,
        "graph_version": GRAPH_VERSION,
        "graph_ref": GRAPH_REF,
        "graph_checksum": GRAPH_CHECKSUM,
        "origin": origin,
        "atomic_group": f"group-{effect_id}",
        "identity_scope_ref": IDENTITY_SCOPE_REF,
        "subject_scope_ref": SUBJECT_SCOPE_REF,
        "handler": "research.artifact@1",
        "candidate_refs": (f"candidate://run-1/{effect_id}",),
    }
    if origin == "worker":
        common.update(
            step_id="publish_artifacts",
            node_id="publish_artifacts",
            node_instance_id=node_instance_id or f"node:{effect_id}",
            activity_id=f"activity:{node_instance_id or effect_id}",
            worker_result_ref=checksum_for({"worker": effect_id}),
            candidate_checksum=checksum_for({"candidate": effect_id}),
        )
    else:
        common.update(
            terminal_action="publish_terminal",
            state_checksum=checksum_for({"state": effect_id}),
            completion_input_ref=checksum_for({"completion": effect_id}),
        )
    return HarnessSideEffectIntent(**common)


def _decision(
    intent: HarnessSideEffectIntent,
    *,
    attempt_limit: int = 2,
    command_ordinal: int = 1,
) -> HarnessSideEffectDecision:
    return HarnessSideEffectDecision(
        decision_id=f"decision-{intent.effect_id}-{intent.node_instance_id}",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        graph_id=intent.graph_id,
        graph_version=intent.graph_version,
        graph_ref=intent.graph_ref,
        graph_checksum=intent.graph_checksum,
        handler=intent.handler,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=command_ordinal,
        causation_id=f"event-{intent.effect_id}",
        disposition="prepared" if intent.origin.value == "worker" else "accepted",
        node_id=intent.node_id,
        node_instance_id=intent.node_instance_id,
        activity_id=intent.activity_id,
        attempt=intent.attempt,
        step_id=intent.step_id,
        terminal_action=intent.terminal_action,
        worker_result_ref=intent.worker_result_ref,
        terminal_state_ref=intent.state_checksum,
        approval_evidence_ref=checksum_for({"approval": intent.effect_id}),
        effect_attempt_limit=attempt_limit,
        decided_at=COMMITTED_AT,
    )


def _outcome(
    decision: HarnessSideEffectDecision,
    *,
    disposition: HarnessSideEffectDisposition
    | str = HarnessSideEffectDisposition.PREPARED,
) -> HarnessSideEffectOutcome:
    normalized = HarnessSideEffectDisposition(disposition)
    return HarnessSideEffectOutcome(
        outcome_id=f"outcome-{decision.effect_id}-{decision.node_instance_id}",
        effect_id=decision.effect_id,
        decision_ref=decision.checksum,
        run_id=decision.run_id,
        graph_id=decision.graph_id,
        graph_version=decision.graph_version,
        graph_ref=decision.graph_ref,
        graph_checksum=decision.graph_checksum,
        origin=decision.origin,
        kind=decision.kind,
        handler=decision.handler,
        idempotency_key=decision.idempotency_key,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
        atomic_group=decision.atomic_group,
        node_id=decision.node_id,
        node_instance_id=decision.node_instance_id,
        activity_id=decision.activity_id,
        step_id=decision.step_id,
        terminal_action=decision.terminal_action,
        attempt=decision.attempt,
        disposition=normalized,
        candidate_refs=(f"candidate://run-1/{decision.effect_id}",),
        public_refs=(f"artifact://run-1/{decision.effect_id}",)
        if normalized is HarnessSideEffectDisposition.ACCEPTED
        else (),
        result_ref=checksum_for({"result": decision.effect_id}),
        committed_at=COMMITTED_AT,
    )


def test_sqlite_store_is_file_backed_wal_and_implements_ports(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert isinstance(store, HarnessSideEffectStorePort)
    assert isinstance(store, HarnessFencedSideEffectStorePort)
    assert isinstance(store, HarnessSideEffectReaderPort)
    assert store.durability_policy == {
        "journal_mode": "WAL",
        "synchronous": "FULL",
        "busy_timeout_ms": 5000,
        "host_scope": "single-host",
    }
    with sqlite3.connect(store.database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "harness_side_effect_decisions",
        "harness_side_effect_attempts",
        "harness_side_effect_attempt_leases",
        "harness_side_effect_outcomes",
    } <= tables

    with pytest.raises(ValueError, match="file-backed"):
        SQLiteHarnessSideEffectStore(":memory:")


def test_unknown_future_schema_fails_before_ddl_or_journal_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "harness-side-effects.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE harness_side_effect_store_metadata ("
            "schema_version INTEGER PRIMARY KEY, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO harness_side_effect_store_metadata "
            "(schema_version, created_at) VALUES (999, 'future')"
        )
        connection.execute("CREATE TABLE future_owned_record (value TEXT NOT NULL)")
        before = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    with pytest.raises(HarnessValidationError) as captured:
        SQLiteHarnessSideEffectStore(database)

    assert captured.value.code == "side_effect_store_schema_unsupported"
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == journal_mode
    assert after == before


def test_decision_outcome_and_attempt_survive_reconstruction(tmp_path: Path) -> None:
    intent = _intent()
    decision = _decision(intent)
    outcome = _outcome(decision)
    first = _store(tmp_path)

    assert first.put_decision(decision) == decision
    assert first.put_decision(decision) == decision
    assert first.reserve_attempt(decision) == 1
    assert first.put_outcome(outcome) == outcome
    assert first.put_outcome(outcome) == outcome

    reconstructed = _store(tmp_path)
    assert reconstructed.get_decision(decision.checksum) == decision
    assert reconstructed.list_decisions(run_id="run-1") == (decision,)
    assert (
        reconstructed.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            idempotency_key=intent.idempotency_key,
        )
        == outcome
    )
    assert (
        reconstructed.read_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
        == outcome
    )
    assert (
        reconstructed.attempt_count(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
        == 1
    )
    reconstructed.verify_integrity()


def test_same_effect_id_different_node_instances_are_storage_isolated(
    tmp_path: Path,
) -> None:
    left = _intent(effect_id="shared-effect", node_instance_id="publish:1")
    right = _intent(effect_id="shared-effect", node_instance_id="publish:2")
    left_decision = _decision(left)
    right_decision = _decision(right)
    store = _store(tmp_path)

    store.put_decision(left_decision)
    store.put_decision(right_decision)
    left_outcome = store.put_outcome(_outcome(left_decision))
    right_outcome = store.put_outcome(_outcome(right_decision))

    assert left_outcome.node_instance_id == "publish:1"
    assert right_outcome.node_instance_id == "publish:2"
    assert (
        store.get_outcome(
            effect_id=left.effect_id,
            identity_scope_ref=left.identity_scope_ref,
            subject_scope_ref=left.subject_scope_ref,
            idempotency_key=left.idempotency_key,
        )
        == left_outcome
    )
    with pytest.raises(HarnessValidationError, match="ambiguous"):
        store.read_outcome(
            effect_id=left.effect_id,
            identity_scope_ref=left.identity_scope_ref,
            subject_scope_ref=left.subject_scope_ref,
        )
    with pytest.raises(HarnessValidationError, match="ambiguous"):
        store.set_disposition(
            effect_id=left.effect_id,
            disposition="quarantine",
            identity_scope_ref=left.identity_scope_ref,
            subject_scope_ref=left.subject_scope_ref,
        )
    store.verify_integrity()


def test_same_effect_id_different_node_instances_have_independent_attempt_fences(
    tmp_path: Path,
) -> None:
    left = _intent(effect_id="shared-effect-fence", node_instance_id="publish:1")
    right = _intent(effect_id="shared-effect-fence", node_instance_id="publish:2")
    left_decision = _decision(left)
    right_decision = _decision(right)
    store = _store(tmp_path)

    store.put_decision(left_decision)
    store.put_decision(right_decision)
    left_attempt = store.acquire_attempt(
        left_decision,
        owner_id="owner:left",
        lease_id="lease:left",
    )
    right_attempt = store.acquire_attempt(
        right_decision,
        owner_id="owner:right",
        lease_id="lease:right",
    )

    assert left_attempt.node_instance_id == "publish:1"
    assert right_attempt.node_instance_id == "publish:2"
    assert left_attempt.attempt == right_attempt.attempt == 1
    store.verify_integrity()


@pytest.mark.parametrize("origin", ["worker", "controller_terminal"])
def test_attempt_exhaustion_is_persisted_for_worker_and_terminal_effects(
    tmp_path: Path,
    origin: str,
) -> None:
    intent = _intent(effect_id=f"effect-{origin}", origin=origin)
    decision = _decision(intent, attempt_limit=2)
    store = _store(tmp_path)
    store.put_decision(decision)

    assert store.reserve_attempt(decision) == 1
    assert _store(tmp_path).reserve_attempt(decision) == 2
    reconstructed = _store(tmp_path)
    with pytest.raises(HarnessValidationError) as captured:
        reconstructed.reserve_attempt(decision)
    assert captured.value.code == "effect_retry_exhausted"
    assert captured.value.details == {
        "code": "effect_retry_exhausted",
        "effect_id": intent.effect_id,
        "attempt_count": 2,
        "attempt_limit": 2,
    }


def test_scope_and_idempotency_mismatches_fail_closed_after_restart(
    tmp_path: Path,
) -> None:
    intent = _intent()
    decision = _decision(intent)
    store = _store(tmp_path)
    store.put_decision(decision)
    store.reserve_attempt(decision)
    store.put_outcome(_outcome(decision))
    reconstructed = _store(tmp_path)
    other_scope = checksum_for({"tenant_id": "tenant-other"})

    with pytest.raises(HarnessValidationError, match="scope mismatch"):
        reconstructed.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=other_scope,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            idempotency_key=intent.idempotency_key,
        )
    with pytest.raises(HarnessValidationError, match="idempotency identity mismatch"):
        reconstructed.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            idempotency_key="wrong-idempotency-key",
        )
    with pytest.raises(HarnessValidationError, match="attempt scope mismatch"):
        reconstructed.attempt_count(
            effect_id=intent.effect_id,
            identity_scope_ref=other_scope,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
    with pytest.raises(HarnessValidationError, match="scope mismatch"):
        reconstructed.set_disposition(
            effect_id=intent.effect_id,
            disposition="quarantine",
            identity_scope_ref=other_scope,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )


def test_disposition_update_is_atomic_idempotent_and_restart_durable(
    tmp_path: Path,
) -> None:
    intent = _intent()
    decision = _decision(intent)
    store = _store(tmp_path)
    store.put_decision(decision)
    prepared = store.put_outcome(_outcome(decision))

    quarantined = store.set_disposition(
        effect_id=intent.effect_id,
        disposition="quarantine",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    )
    assert quarantined is not None
    assert quarantined.disposition is HarnessSideEffectDisposition.QUARANTINE
    assert quarantined.checksum != prepared.checksum
    assert (
        store.set_disposition(
            effect_id=intent.effect_id,
            disposition="quarantine",
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
        == quarantined
    )

    reconstructed = _store(tmp_path)
    assert (
        reconstructed.read_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
        == quarantined
    )
    with pytest.raises(HarnessValidationError, match="cannot publish"):
        reconstructed.set_disposition(
            effect_id=intent.effect_id,
            disposition="accepted",
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )


def test_immutable_decision_and_outcome_collisions_are_rejected(tmp_path: Path) -> None:
    intent = _intent()
    decision = _decision(intent)
    store = _store(tmp_path)
    store.put_decision(decision)

    conflicting_decision = replace(
        decision,
        command_ordinal=decision.command_ordinal + 1,
        checksum=None,
    )
    with pytest.raises(HarnessValidationError, match="decision identity is immutable"):
        store.put_decision(conflicting_decision)

    outcome = _outcome(decision)
    store.put_outcome(outcome)
    conflicting_outcome = replace(
        outcome,
        result_ref=checksum_for({"result": "different"}),
        checksum=None,
    )
    with pytest.raises(HarnessValidationError, match="outcome identity is immutable"):
        store.put_outcome(conflicting_outcome)


def test_concurrent_attempt_reservations_never_exceed_durable_limit(
    tmp_path: Path,
) -> None:
    intent = _intent()
    decision = _decision(intent, attempt_limit=4)
    _store(tmp_path).put_decision(decision)

    def reserve() -> int | str:
        try:
            return _store(tmp_path).reserve_attempt(decision)
        except HarnessValidationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: reserve(), range(8)))

    assert sorted(result for result in results if isinstance(result, int)) == [
        1,
        2,
        3,
        4,
    ]
    assert results.count("effect_retry_exhausted") == 4
    assert (
        _store(tmp_path).attempt_count(
            effect_id=intent.effect_id,
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
        )
        == 4
    )


def test_fenced_attempt_is_restart_durable_and_requires_confirmed_termination(
    tmp_path: Path,
) -> None:
    clock = _MutableClock()
    intent = _intent(effect_id="effect-fenced")
    decision = _decision(intent, attempt_limit=3)
    store = _store(tmp_path, attempt_lease_seconds=30, clock=clock)
    store.put_decision(decision)

    first = store.acquire_attempt(
        decision,
        owner_id="owner-1",
        lease_id="lease-1",
    )
    reconstructed = _store(tmp_path, attempt_lease_seconds=30, clock=clock)
    assert (
        reconstructed.acquire_attempt(
            decision,
            owner_id="owner-1",
            lease_id="lease-1",
        )
        == first
    )
    assert reconstructed.renew_attempt(first) == first
    with pytest.raises(HarnessValidationError) as active:
        reconstructed.acquire_attempt(
            decision,
            owner_id="owner-2",
            lease_id="lease-2",
        )
    assert active.value.code == "side_effect_attempt_in_progress"

    clock.advance(5)
    renewed = reconstructed.renew_attempt(first)
    assert renewed.lease_expires_at > first.lease_expires_at
    clock.advance(31)
    with pytest.raises(HarnessValidationError) as expired:
        reconstructed.acquire_attempt(
            decision,
            owner_id="owner-2",
            lease_id="lease-2",
        )
    assert expired.value.code == "side_effect_attempt_termination_unconfirmed"

    indeterminate = reconstructed.finish_attempt(
        renewed,
        termination_confirmed=False,
    )
    assert indeterminate.status is HarnessSideEffectAttemptStatus.INDETERMINATE
    with pytest.raises(HarnessValidationError) as unresolved:
        reconstructed.acquire_attempt(
            decision,
            owner_id="owner-2",
            lease_id="lease-2",
        )
    assert unresolved.value.code == "side_effect_attempt_termination_unconfirmed"

    reconstructed.finish_attempt(renewed, termination_confirmed=True)
    second = reconstructed.acquire_attempt(
        decision,
        owner_id="owner-2",
        lease_id="lease-2",
    )
    assert second.attempt == second.fencing_generation == 2
    assert second.idempotency_key == first.idempotency_key
    with pytest.raises(HarnessValidationError) as stale:
        reconstructed.complete_attempt(first, _outcome(decision))
    assert stale.value.code == "stale_side_effect_attempt"

    committed = reconstructed.complete_attempt(second, _outcome(decision))
    assert committed.attempt_id == second.attempt_id
    assert committed.fencing_generation == second.fencing_generation
    assert committed.schema_version == "newsroom.harness-side-effect-outcome/v3"
    persisted = _store(tmp_path, clock=clock)
    assert (
        persisted.get_outcome(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
            idempotency_key=decision.idempotency_key,
        )
        == committed
    )
    completed_attempt = persisted.get_attempt(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert completed_attempt.status is HarnessSideEffectAttemptStatus.TERMINATED
    assert completed_attempt.outcome_ref == committed.checksum
    quarantined = persisted.set_disposition(
        effect_id=decision.effect_id,
        disposition="quarantine",
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert quarantined is not None
    assert (
        persisted.get_attempt(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
        ).outcome_ref
        == quarantined.checksum
    )
    with pytest.raises(HarnessValidationError) as bypass:
        persisted.put_outcome(_outcome(decision))
    assert bypass.value.code == "fenced_side_effect_attempt_required"
    persisted.verify_integrity()


def test_concurrent_fenced_attempt_acquisition_allows_one_active_owner(
    tmp_path: Path,
) -> None:
    intent = _intent(effect_id="effect-concurrent-fenced")
    decision = _decision(intent, attempt_limit=4)
    _store(tmp_path).put_decision(decision)

    def acquire(index: int) -> int | str:
        try:
            return (
                _store(tmp_path)
                .acquire_attempt(
                    decision,
                    owner_id=f"owner-{index}",
                    lease_id=f"lease-{index}",
                )
                .attempt
            )
        except HarnessValidationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(acquire, range(8)))

    assert results.count(1) == 1
    assert results.count("side_effect_attempt_in_progress") == 7
    assert (
        _store(tmp_path).attempt_count(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
        )
        == 1
    )


def test_integrity_rejects_v2_outcome_bound_to_another_attempt_identity(
    tmp_path: Path,
) -> None:
    intent = _intent(effect_id="effect-tampered-fence")
    decision = _decision(intent)
    store = _store(tmp_path)
    store.put_decision(decision)
    attempt = store.acquire_attempt(
        decision,
        owner_id="owner-tampered-fence",
        lease_id="lease-tampered-fence",
    )
    committed = store.complete_attempt(attempt, _outcome(decision))
    completed_attempt = store.get_attempt(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert completed_attempt is not None
    tampered = replace(
        committed,
        attempt_id=checksum_for({"attempt": "another"}),
        checksum=None,
    )
    relinked_attempt = completed_attempt.relinked_outcome(tampered.checksum)

    with sqlite3.connect(store.database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "UPDATE harness_side_effect_outcomes "
            "SET outcome_ref = ?, outcome_json = ? WHERE outcome_ref = ?",
            (
                tampered.checksum,
                stable_json_dumps(tampered.to_dict()),
                committed.checksum,
            ),
        )
        connection.execute(
            "UPDATE harness_side_effect_attempt_leases "
            "SET outcome_ref = ?, attempt_json = ? WHERE attempt_id = ?",
            (
                tampered.checksum,
                stable_json_dumps(relinked_attempt.to_dict()),
                attempt.attempt_id,
            ),
        )

    with pytest.raises(HarnessValidationError) as captured:
        _store(tmp_path)
    assert captured.value.code == "side_effect_store_corrupt"
    assert "conflicts with its lease" in str(captured.value)


def test_concurrent_reconciliation_commits_one_outcome_without_new_fence(
    tmp_path: Path,
) -> None:
    intent = _intent(effect_id="effect-concurrent-reconciliation")
    decision = _decision(intent, attempt_limit=3)
    initial_store = _store(tmp_path)
    initial_store.put_decision(decision)
    attempt = initial_store.acquire_attempt(
        decision,
        owner_id="crashed-owner",
        lease_id="crashed-lease",
    )
    stores = (_store(tmp_path), _store(tmp_path))
    barrier = Barrier(2)

    def reconcile(store: SQLiteHarnessSideEffectStore) -> HarnessSideEffectOutcome:
        barrier.wait(timeout=5)
        return store.reconcile_attempt(attempt, _outcome(decision))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(reconcile, stores))

    assert outcomes[0] == outcomes[1]
    assert outcomes[0].attempt_id == attempt.attempt_id
    assert outcomes[0].fencing_generation == 1
    persisted = _store(tmp_path)
    completed = persisted.get_attempt(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert completed is not None
    assert completed.status is HarnessSideEffectAttemptStatus.TERMINATED
    assert completed.fencing_generation == 1
    assert completed.outcome_ref == outcomes[0].checksum
    assert (
        persisted.attempt_count(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
        )
        == 1
    )
    with sqlite3.connect(persisted.database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM harness_side_effect_outcomes"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM harness_side_effect_attempt_leases"
            ).fetchone()[0]
            == 1
        )
    persisted.verify_integrity()


def test_v1_schema_migrates_without_reclassifying_serial_attempts(
    tmp_path: Path,
) -> None:
    intent = _intent(effect_id="effect-v1-migration")
    decision = _decision(intent, attempt_limit=3)
    store = _store(tmp_path)
    store.put_decision(decision)
    assert store.reserve_attempt(decision) == 1

    with sqlite3.connect(store.database) as connection:
        connection.execute("DROP TABLE harness_side_effect_attempt_leases")
        connection.execute(
            "UPDATE harness_side_effect_store_metadata SET schema_version = 1"
        )

    migrated = _store(tmp_path)
    with sqlite3.connect(migrated.database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM harness_side_effect_store_metadata"
        ).fetchone()[0]
    assert version == 3
    assert migrated.reserve_attempt(decision) == 2
    with pytest.raises(HarnessValidationError) as unfenced:
        migrated.acquire_attempt(
            decision,
            owner_id="owner-v2",
            lease_id="lease-v2",
        )
    assert unfenced.value.code == "side_effect_attempt_termination_unconfirmed"


def test_v2_schema_migrates_effect_only_fenced_identity(
    tmp_path: Path,
) -> None:
    intent = _intent(
        effect_id="effect-v2-identity-migration",
        node_instance_id="publish:legacy",
    )
    decision = _decision(intent, attempt_limit=3)
    store = _store(tmp_path)
    store.put_decision(decision)
    legacy_attempt = store.acquire_attempt(
        decision,
        owner_id="legacy-owner",
        lease_id="legacy-lease",
    )

    with sqlite3.connect(store.database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "UPDATE harness_side_effect_store_metadata SET schema_version = 2"
        )
        connection.execute(
            "UPDATE harness_side_effect_decisions SET effect_id = ?",
            (decision.effect_id,),
        )
        connection.execute(
            "UPDATE harness_side_effect_attempts SET effect_id = ?",
            (decision.effect_id,),
        )
        connection.execute(
            "UPDATE harness_side_effect_attempt_leases SET effect_id = ?, attempt_json = ?",
            (
                decision.effect_id,
                stable_json_dumps(
                    {
                        key: value
                        for key, value in json_loads(
                            stable_json_dumps(legacy_attempt.to_dict())
                        ).items()
                        if key
                        not in {
                            "run_id",
                            "origin",
                            "terminal_action",
                            "activity_attempt",
                        }
                    }
                    | {"checksum": None}
                ),
            ),
        )

    migrated = _store(tmp_path)
    with sqlite3.connect(migrated.database) as connection:
        version = connection.execute(
            "SELECT schema_version FROM harness_side_effect_store_metadata"
        ).fetchone()[0]
        stored_effect_id = connection.execute(
            "SELECT effect_id FROM harness_side_effect_decisions"
        ).fetchone()[0]
    assert version == 3
    assert stored_effect_id != decision.effect_id
    restored_attempt = migrated.get_attempt(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert restored_attempt is not None
    assert restored_attempt.node_instance_id == "publish:legacy"
    assert restored_attempt.run_id == decision.run_id
    assert restored_attempt.activity_attempt == decision.attempt
    assert migrated.attempt_count(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    ) == 1
    migrated.verify_integrity()
