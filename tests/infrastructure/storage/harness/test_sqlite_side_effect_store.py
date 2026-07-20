from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

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
from infrastructure.storage.harness import SQLiteHarnessSideEffectStore


IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "tenant-1"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})
COMMITTED_AT = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> SQLiteHarnessSideEffectStore:
    return SQLiteHarnessSideEffectStore(tmp_path / "harness-side-effects.sqlite3")


def _intent(
    *,
    effect_id: str = "effect-worker-1",
    origin: str = "worker",
) -> HarnessSideEffectIntent:
    common = {
        "effect_id": effect_id,
        "kind": "artifact",
        "run_id": "run-1",
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
        decision_id=f"decision-{intent.effect_id}",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=intent.handler,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=command_ordinal,
        causation_id=f"event-{intent.effect_id}",
        disposition="prepared" if intent.origin.value == "worker" else "accepted",
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
    disposition: HarnessSideEffectDisposition | str = HarnessSideEffectDisposition.PREPARED,
) -> HarnessSideEffectOutcome:
    normalized = HarnessSideEffectDisposition(disposition)
    return HarnessSideEffectOutcome(
        outcome_id=f"outcome-{decision.effect_id}",
        effect_id=decision.effect_id,
        decision_ref=decision.checksum,
        run_id=decision.run_id,
        kind=decision.kind,
        handler=decision.handler,
        idempotency_key=decision.idempotency_key,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
        atomic_group=decision.atomic_group,
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
        "harness_side_effect_outcomes",
    } <= tables

    with pytest.raises(ValueError, match="file-backed"):
        SQLiteHarnessSideEffectStore(":memory:")


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
    assert reconstructed.get_outcome(
        effect_id=intent.effect_id,
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
        idempotency_key=intent.idempotency_key,
    ) == outcome
    assert reconstructed.read_outcome(
        effect_id=intent.effect_id,
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == outcome
    assert reconstructed.attempt_count(
        effect_id=intent.effect_id,
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == 1
    reconstructed.verify_integrity()


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
    assert store.set_disposition(
        effect_id=intent.effect_id,
        disposition="quarantine",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == quarantined

    reconstructed = _store(tmp_path)
    assert reconstructed.read_outcome(
        effect_id=intent.effect_id,
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == quarantined
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

    assert sorted(result for result in results if isinstance(result, int)) == [1, 2, 3, 4]
    assert results.count("effect_retry_exhausted") == 4
    assert _store(tmp_path).attempt_count(
        effect_id=intent.effect_id,
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
    ) == 4
