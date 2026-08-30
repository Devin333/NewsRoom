from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.control_plane.errors import HarnessValidationError

from backend.research.domain import (
    ReaderIssue,
    ReaderRepairCase,
    ReaderRepairSkillCandidateSeed,
    ReaderRepairStrategy,
)
from backend.research.graphs import build_reader_repair_memory_worker_result
from backend.research.ports.repair_memory import (
    READER_REPAIR_MEMORY_EFFECT_KIND,
    READER_REPAIR_MEMORY_HANDLER_REF,
    READER_REPAIR_MEMORY_SCHEMA_VERSION,
    ReaderRepairMemoryCommitReceipt,
    ReaderRepairMemoryCommitRequest,
    reader_repair_case_memory_ref,
    reader_repair_strategy_memory_ref,
)
from infrastructure.research.reader_repair_memory_side_effect import (
    ReaderRepairMemorySideEffectHandler,
)


_IDENTITY_SCOPE = checksum_for({"tenant_id": "tenant-a", "user_id": "user-a"})
_SUBJECT_SCOPE = checksum_for({"paper_id": "paper-1"})
_MEMORY_GATE_REF = "ReaderRepairMemoryPolicyGate@1"
_COMMITTED_AT = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
_GRAPH_ID = "research.reader-repair"
_GRAPH_VERSION = "2"
_GRAPH_REF = f"{_GRAPH_ID}@{_GRAPH_VERSION}"
_GRAPH_CHECKSUM = checksum_for({"graph_id": _GRAPH_ID, "graph_version": _GRAPH_VERSION})


class _AtomicMemoryCommitPort:
    def __init__(self, *, conflicting_receipt: bool = False) -> None:
        self.conflicting_receipt = conflicting_receipt
        self.calls: list[ReaderRepairMemoryCommitRequest] = []
        self.physical_commits = 0
        self._requests: dict[str, ReaderRepairMemoryCommitRequest] = {}
        self._receipts: dict[str, ReaderRepairMemoryCommitReceipt] = {}

    def commit(
        self,
        request: ReaderRepairMemoryCommitRequest,
    ) -> ReaderRepairMemoryCommitReceipt:
        self.calls.append(request)
        existing = self._receipts.get(request.idempotency_key)
        if existing is not None:
            if self._requests[request.idempotency_key] != request:
                raise AssertionError("idempotency key was reused for another request")
            return existing
        self.physical_commits += 1
        projection = request.projection
        strategy_refs = tuple(
            reader_repair_strategy_memory_ref(strategy, version=1)
            for strategy in projection.strategies
        )
        if self.conflicting_receipt:
            strategy_refs = ("memory://research.reader_repair/strategy/wrong",)
        receipt = ReaderRepairMemoryCommitReceipt(
            receipt_id=f"reader-repair-memory-receipt:{request.request_id}",
            request_ref=request.checksum,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            idempotency_key=request.idempotency_key,
            namespace=projection.candidate.namespace,
            case_ref=reader_repair_case_memory_ref(
                projection.repair_case,
                version=1,
            ),
            case_version=1,
            strategy_refs=strategy_refs,
            strategy_versions=tuple(1 for _strategy in projection.strategies),
            committed_at=_COMMITTED_AT,
        )
        self._requests[request.idempotency_key] = request
        self._receipts[request.idempotency_key] = receipt
        return receipt


def test_prepare_is_write_free_and_terminal_commit_is_atomic_and_idempotent() -> None:
    port, store, handler = _handler()
    worker_intent, worker_decision = _worker_authority()
    store.put_decision(worker_decision)

    prepared = handler.prepare(worker_intent, worker_decision)

    assert port.calls == []
    assert port.physical_commits == 0
    assert prepared.disposition is HarnessSideEffectDisposition.PREPARED
    assert prepared.public_refs == ()
    assert prepared.result_ref == prepared.metadata["memory_candidate_checksum"]
    store.put_outcome(prepared)

    terminal_intent, terminal_decision = _terminal_authority(prepared)
    store.put_decision(terminal_decision)
    first = handler.commit(terminal_intent, terminal_decision)
    second = handler.commit(terminal_intent, terminal_decision)

    projection = port.calls[0].projection
    request = port.calls[0]
    assert first == second
    assert port.physical_commits == 1
    assert len(port.calls) == 2
    assert first.disposition is HarnessSideEffectDisposition.ACCEPTED
    assert first.public_refs == (
        reader_repair_case_memory_ref(projection.repair_case, version=1),
        *(
            reader_repair_strategy_memory_ref(item, version=1)
            for item in projection.strategies
        ),
    )
    assert ReaderRepairMemoryCommitRequest.from_dict(request.to_dict()) == request
    assert ReaderRepairMemoryCommitReceipt.from_dict(
        first.metadata["commit_receipt"]
    ).public_refs == first.public_refs
    with pytest.raises(TypeError):
        request.candidate.content["repair_case"] = {}  # type: ignore[index]

    store.put_outcome(first)
    recovered = handler.commit(terminal_intent, terminal_decision)

    assert recovered == first
    assert len(port.calls) == 2
    assert port.physical_commits == 1


def test_memory_worker_emits_proposed_candidate_and_no_commit_authority() -> None:
    result = _worker_result()
    intent = result.effect_intent

    assert intent is not None
    assert intent.origin is HarnessSideEffectOrigin.WORKER
    assert intent.kind == READER_REPAIR_MEMORY_EFFECT_KIND
    assert str(intent.handler) == READER_REPAIR_MEMORY_HANDLER_REF
    assert intent.payload["schema_version"] == READER_REPAIR_MEMORY_SCHEMA_VERSION
    assert result.output["memory_write_candidate"]["status"] == "proposed"
    assert result.output["memory_write_candidate"]["metadata"][
        "active_skill_mutation"
    ] is False
    assert "memory_ref" not in result.output
    assert "public_refs" not in result.output


def test_worker_authority_cannot_invoke_terminal_commit() -> None:
    port, _store, handler = _handler()
    intent, decision = _worker_authority()

    with pytest.raises(
        HarnessValidationError,
        match="controller-terminal authority",
    ):
        handler.commit(intent, decision)

    assert port.calls == []


def test_terminal_commit_fails_closed_without_exact_prepared_outcome() -> None:
    port, store, handler = _handler()
    worker_intent, _worker_decision = _worker_authority()
    missing = checksum_for({"prepared": "missing"})
    terminal_intent, terminal_decision = _terminal_authority(
        None,
        prepared_ref=missing,
        candidate_refs=worker_intent.candidate_refs,
        atomic_group=worker_intent.atomic_group,
    )
    store.put_decision(terminal_decision)

    with pytest.raises(HarnessValidationError) as captured:
        handler.commit(terminal_intent, terminal_decision)

    assert captured.value.code == "reader_repair_prepared_outcome_missing"
    assert port.calls == []


@pytest.mark.parametrize(
    "tamper",
    ("namespace", "candidate_checksum", "skill_authority"),
)
def test_prepare_rejects_rehashed_candidate_substitution(tamper: str) -> None:
    port, _store, handler = _handler()
    intent, _decision = _worker_authority()
    raw_candidate = _deep_copy(intent.payload["memory_write_candidate"])
    assert isinstance(raw_candidate, dict)
    if tamper == "namespace":
        raw_candidate["namespace"] = "shared"
    elif tamper == "skill_authority":
        raw_candidate["metadata"]["publish"] = True
    payload_checksum = checksum_for(raw_candidate)
    payload = {
        "schema_version": READER_REPAIR_MEMORY_SCHEMA_VERSION,
        "memory_write_candidate": raw_candidate,
        "memory_candidate_checksum": (
            checksum_for({"wrong": True})
            if tamper == "candidate_checksum"
            else payload_checksum
        ),
    }
    rebound = _rebind_intent(intent, payload=payload)
    decision = _worker_decision(rebound)

    with pytest.raises(HarnessValidationError):
        handler.prepare(rebound, decision)

    assert port.calls == []


def test_prepare_rejects_authorization_scope_substitution() -> None:
    port, _store, handler = _handler()
    intent, _decision = _worker_authority()
    decision = _worker_decision(
        intent,
        identity_scope_ref=checksum_for({"tenant_id": "other"}),
    )

    with pytest.raises(HarnessValidationError) as captured:
        handler.prepare(intent, decision)

    assert captured.value.code == "reader_repair_memory_authority_mismatch"
    assert port.calls == []


def test_terminal_rejects_adapter_receipt_that_does_not_match_bundle() -> None:
    port, store, handler = _handler(conflicting_receipt=True)
    worker_intent, worker_decision = _worker_authority()
    store.put_decision(worker_decision)
    prepared = handler.prepare(worker_intent, worker_decision)
    store.put_outcome(prepared)
    terminal_intent, terminal_decision = _terminal_authority(prepared)
    store.put_decision(terminal_decision)

    with pytest.raises(HarnessValidationError) as captured:
        handler.commit(terminal_intent, terminal_decision)

    assert captured.value.code == "reader_repair_memory_receipt_conflict"
    assert port.physical_commits == 1


def _handler(
    *,
    conflicting_receipt: bool = False,
) -> tuple[
    _AtomicMemoryCommitPort,
    InMemoryHarnessSideEffectStore,
    ReaderRepairMemorySideEffectHandler,
]:
    port = _AtomicMemoryCommitPort(conflicting_receipt=conflicting_receipt)
    store = InMemoryHarnessSideEffectStore()
    return port, store, ReaderRepairMemorySideEffectHandler(
        commit_port=port,
        side_effect_store=store,
    )


def _worker_result():
    repair_case = _repair_case()
    return build_reader_repair_memory_worker_result(
        run_id="repair-run-1",
        repair_case=repair_case,
        strategy_candidate_bundle=_strategy_bundle(repair_case),
        identity_scope_ref=_IDENTITY_SCOPE,
        subject_scope_ref=_SUBJECT_SCOPE,
        graph_id=_GRAPH_ID,
        graph_version=_GRAPH_VERSION,
        graph_ref=_GRAPH_REF,
        graph_checksum=_GRAPH_CHECKSUM,
        node_id="repair_memory_write",
        node_instance_id="node:repair-run-1:repair-memory",
        activity_id="activity:repair-run-1:repair-memory",
    )


def _worker_authority() -> tuple[HarnessSideEffectIntent, HarnessSideEffectDecision]:
    result = _worker_result()
    assert result.effect_intent is not None
    intent = _rebind_intent(
        result.effect_intent,
        worker_result_ref=result.candidate_result_ref,
    )
    return intent, _worker_decision(intent)


def _worker_decision(
    intent: HarnessSideEffectIntent,
    **overrides: Any,
) -> HarnessSideEffectDecision:
    values = {
        "decision_id": f"reader-repair-memory-decision:{intent.effect_id}",
        "intent_ref": intent.checksum,
        "effect_id": intent.effect_id,
        "kind": intent.kind,
        "origin": intent.origin,
        "run_id": intent.run_id,
        "graph_id": intent.graph_id,
        "graph_version": intent.graph_version,
        "graph_ref": intent.graph_ref,
        "graph_checksum": intent.graph_checksum,
        "handler": intent.handler,
        "identity_scope_ref": intent.identity_scope_ref,
        "subject_scope_ref": intent.subject_scope_ref,
        "atomic_group": intent.atomic_group,
        "idempotency_key": intent.idempotency_key,
        "command_ordinal": 1,
        "causation_id": "command:reader-repair-worker",
        "disposition": HarnessSideEffectDisposition.PREPARED,
        "step_id": intent.step_id,
        "node_id": intent.node_id,
        "node_instance_id": intent.node_instance_id,
        "activity_id": intent.activity_id,
        "attempt": intent.attempt,
        "worker_result_ref": intent.worker_result_ref,
        "gate_refs": (_MEMORY_GATE_REF,),
        "gate_result_refs": (checksum_for({"gate": "memory"}),),
        "aggregate_verdict_ref": checksum_for({"verdict": "passed"}),
        "approval_evidence_ref": checksum_for({"approval": "not-required"}),
        "budget_ref": checksum_for({"budget": "bounded"}),
    }
    values.update(overrides)
    return HarnessSideEffectDecision(**values)


def _terminal_authority(
    prepared,
    *,
    prepared_ref: str | None = None,
    candidate_refs: tuple[str, ...] | None = None,
    atomic_group: str | None = None,
) -> tuple[HarnessSideEffectIntent, HarnessSideEffectDecision]:
    if prepared is not None:
        prepared_ref = prepared.checksum
        candidate_refs = prepared.candidate_refs
        atomic_group = prepared.atomic_group
    assert prepared_ref is not None
    assert candidate_refs is not None
    assert atomic_group is not None
    intent = HarnessSideEffectIntent(
        effect_id="reader-repair-memory-terminal:repair-run-1",
        kind=READER_REPAIR_MEMORY_EFFECT_KIND,
        run_id="repair-run-1",
        graph_id=_GRAPH_ID,
        graph_version=_GRAPH_VERSION,
        graph_ref=_GRAPH_REF,
        graph_checksum=_GRAPH_CHECKSUM,
        origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL,
        atomic_group=atomic_group,
        identity_scope_ref=_IDENTITY_SCOPE,
        subject_scope_ref=_SUBJECT_SCOPE,
        terminal_action="complete_run",
        state_checksum=checksum_for({"state": "terminal"}),
        completion_input_ref=checksum_for({"completion": "terminal"}),
        handler=READER_REPAIR_MEMORY_HANDLER_REF,
        payload={
            "prepared_outcome_refs": [prepared_ref],
            "history_cutoff": "event-before-terminal",
        },
        candidate_refs=candidate_refs,
    )
    decision = HarnessSideEffectDecision(
        decision_id="reader-repair-memory-decision:terminal",
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
        command_ordinal=2,
        causation_id="command:reader-repair-terminal",
        disposition=HarnessSideEffectDisposition.ACCEPTED,
        terminal_action=intent.terminal_action,
        terminal_state_ref=intent.state_checksum,
        gate_refs=(_MEMORY_GATE_REF,),
        gate_result_refs=(checksum_for({"gate": "memory-terminal"}),),
        aggregate_verdict_ref=checksum_for({"verdict": "terminal-passed"}),
        approval_evidence_ref=checksum_for({"approval": "not-required-terminal"}),
        budget_ref=checksum_for({"budget": "terminal-bounded"}),
    )
    return intent, decision


def _rebind_intent(
    intent: HarnessSideEffectIntent,
    *,
    payload: dict[str, Any] | None = None,
    worker_result_ref: str | None = None,
) -> HarnessSideEffectIntent:
    rebound_payload = dict(intent.payload) if payload is None else payload
    rebound_worker_ref = worker_result_ref or intent.worker_result_ref
    source = replace(
        intent,
        payload=rebound_payload,
        worker_result_ref=rebound_worker_ref,
        source_intent_ref=intent.checksum,
        candidate_checksum=checksum_for({"candidate": "unbound"}),
        checksum=None,
    )
    bound_checksum = checksum_for(
        {
            "worker_result_ref": source.worker_result_ref,
            "payload": source.payload,
            "candidate_refs": source.candidate_refs,
            "atomic_group": source.atomic_group,
        }
    )
    return replace(source, candidate_checksum=bound_checksum, checksum=None)


def _repair_case() -> ReaderRepairCase:
    issue = ReaderIssue(
        issue_id="reader-issue-1",
        paper_id="paper-1",
        run_id="repair-run-1",
        issue_type="section_boundary_error",
        error_signature="section-boundary:paper-1",
        symptom="A section boundary is missing.",
        source_refs=["paper://paper-1/section-1"],
        payload_ref="reader-payload://paper-1",
    )
    return ReaderRepairCase(
        repair_case_id="repair-case-1",
        issue=issue,
        repair_strategy="Restore the source-backed section boundary.",
        repair_attempt_refs=["repair-attempt-1"],
        successful=True,
        verification_results=[
            {"gate_name": "ReaderRepairResultGate", "passed": True}
        ],
        payload_before_ref="reader-payload://paper-1",
        payload_after_ref="reader-payload://paper-1/repaired",
        source_refs=issue.source_refs,
        constraints=["preserve source refs"],
        metadata={"active_skill_mutation": False},
    )


def _strategy_bundle(repair_case: ReaderRepairCase) -> dict[str, Any]:
    strategy = ReaderRepairStrategy(
        strategy_id="repair-strategy-1",
        issue_type=repair_case.issue.issue_type,
        applicability="Repeated source-backed section boundary failures.",
        steps=["match signature", "patch region", "verify source lineage"],
        constraints=["preserve source refs"],
        evidence_requirements=["verification_results"],
        confidence=0.9,
        source_case_refs=[repair_case.repair_case_id],
        status="promoted_memory",
    )
    seed = ReaderRepairSkillCandidateSeed(
        seed_id="repair-seed-1",
        strategy=strategy,
        experience_refs=[f"repair-case://{repair_case.repair_case_id}"],
        patch_objective="Prepare governed reader-repair skill candidate input.",
        publishes_skill=False,
        metadata={"requires_harness_skill_evolution": True},
    )
    return {
        "input_bindings": {
            "reader_repair_context_pack": checksum_for({"context": "verified"}),
            "reader_repair_case": checksum_for(repair_case.to_dict()),
        },
        "strategies": [strategy.to_dict()],
        "skill_candidate_seeds": [seed.to_dict()],
    }


def _deep_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_deep_copy(item) for item in value]
    return value
