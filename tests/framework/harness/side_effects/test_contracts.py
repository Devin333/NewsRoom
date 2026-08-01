from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    CountingHarnessSideEffectHandler,
    HarnessSideEffectApprovalEvidence,
    HarnessSideEffectApprovalRequest,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectHandlerBinding,
    HarnessSideEffectIntent,
    HarnessSideEffectRegistry,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
    HarnessTerminalSideEffectPolicy,
    HarnessStepSpec,
    HarnessWorkflowSpec,
    InMemoryHarnessSideEffectApprovalResolver,
    InMemoryHarnessSideEffectStore,
    HarnessValidationError,
)
from framework.harness.side_effects.models import HarnessSideEffectAttemptStatus
from framework.harness.side_effects.ports import HarnessFencedSideEffectStorePort
from framework.harness.side_effects.registry import HarnessSideEffectCapabilities


IDENTITY_SCOPE_REF = checksum_for({"tenant_id": "tenant-1"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})


def _intent(
    *, origin: str = "worker", effect_id: str = "effect-1"
) -> HarnessSideEffectIntent:
    common = {
        "effect_id": effect_id,
        "kind": "artifact",
        "run_id": "run-1",
        "origin": origin,
        "atomic_group": "group-1",
        "identity_scope_ref": IDENTITY_SCOPE_REF,
        "subject_scope_ref": SUBJECT_SCOPE_REF,
        "handler": "research.artifact@1",
        "candidate_refs": ("candidate://run-1/a",),
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
    approval_ref: str | None = None,
    effect_attempt_limit: int = 1,
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
        command_ordinal=1,
        causation_id="harness-event:decision-input",
        disposition=HarnessSideEffectDisposition.PREPARED,
        step_id=intent.step_id,
        terminal_action=intent.terminal_action,
        worker_result_ref=intent.worker_result_ref,
        terminal_state_ref=intent.state_checksum,
        approval_evidence_ref=approval_ref or checksum_for({"not_required": True}),
        effect_attempt_limit=effect_attempt_limit,
    )


def _outcome(decision: HarnessSideEffectDecision) -> HarnessSideEffectOutcome:
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
        disposition="prepared",
        candidate_refs=(f"candidate://{decision.effect_id}",),
        result_ref=checksum_for({"result": decision.effect_id}),
    )


class _MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _FencedHandler:
    def commit(self, intent, authorization):
        return _outcome(authorization)

    def commit_fenced(self, intent, authorization, attempt):
        return _outcome(authorization)

    def request_cancellation(self, attempt) -> None:
        return None

    def confirm_termination(self, attempt) -> bool:
        return True

    def reconcile(self, intent, authorization, attempt):
        return None


def test_intent_json_round_trip_and_deep_immutability() -> None:
    intent = _intent()
    assert HarnessSideEffectIntent.from_dict(intent.to_dict()) == intent
    with pytest.raises(TypeError):
        intent.payload["mutate"] = True  # type: ignore[index]


def test_origin_identity_rules_are_fail_closed() -> None:
    with pytest.raises(HarnessValidationError, match="controller-terminal identity"):
        HarnessSideEffectIntent(
            effect_id="bad",
            kind="artifact",
            run_id="run-1",
            origin=HarnessSideEffectOrigin.WORKER,
            atomic_group="g",
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            step_id="step",
            worker_result_ref=checksum_for({"worker": 1}),
            candidate_checksum=checksum_for({"candidate": 1}),
            terminal_action="complete",
        )

    with pytest.raises(HarnessValidationError, match="requires terminal action"):
        HarnessSideEffectIntent(
            effect_id="bad",
            kind="artifact",
            run_id="run-1",
            origin=HarnessSideEffectOrigin.CONTROLLER_TERMINAL,
            atomic_group="g",
            identity_scope_ref=IDENTITY_SCOPE_REF,
            subject_scope_ref=SUBJECT_SCOPE_REF,
            terminal_action="complete",
        )


def test_registry_is_instance_scoped_and_exact() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    registry = HarnessSideEffectRegistry(
        (HarnessSideEffectHandlerBinding("research.artifact@1", "artifact", handler),)
    )
    assert registry.resolve("research.artifact@1", kind="artifact").handler is handler
    with pytest.raises(HarnessValidationError) as duplicate:
        registry.register(
            HarnessSideEffectHandlerBinding("research.artifact@1", "artifact", handler)
        )
    assert duplicate.value.code == "duplicate_side_effect_handler"
    with pytest.raises(HarnessValidationError) as unknown:
        registry.resolve("research.artifact@2")
    assert unknown.value.code == "unknown_side_effect_handler"
    with pytest.raises(HarnessValidationError) as mismatch:
        registry.resolve("research.artifact@1", kind="memory")
    assert mismatch.value.code == "side_effect_handler_kind_mismatch"


def test_parallel_safe_binding_requires_capabilities_and_fenced_handler() -> None:
    unsafe = HarnessSideEffectHandlerBinding(
        "research.serial@1",
        "artifact",
        CountingHarnessSideEffectHandler(InMemoryHarnessSideEffectStore()),
    )
    assert unsafe.capabilities.missing_for_physical_concurrency() == (
        "cancellation",
        "termination_confirmation",
        "stable_idempotency",
        "fencing",
        "reconciliation",
    )
    capabilities = HarnessSideEffectCapabilities(
        cancellation=True,
        termination_confirmation=True,
        stable_idempotency=True,
        fencing=True,
        reconciliation=True,
    )
    with pytest.raises(HarnessValidationError) as captured:
        HarnessSideEffectHandlerBinding(
            "research.invalid-fenced@1",
            "artifact",
            unsafe.handler,
            capabilities=capabilities,
        )
    assert captured.value.code == "invalid_fenced_side_effect_handler"

    safe = HarnessSideEffectHandlerBinding(
        "research.fenced@1",
        "artifact",
        _FencedHandler(),
        capabilities=capabilities,
    )
    assert safe.capabilities.physical_concurrency_safe


def test_in_memory_fenced_attempt_blocks_overlap_and_rejects_stale_fence() -> None:
    clock = _MutableClock()
    store = InMemoryHarnessSideEffectStore(
        attempt_lease_seconds=30,
        clock=clock,
    )
    assert isinstance(store, HarnessFencedSideEffectStorePort)
    intent = _intent(effect_id="effect-fenced")
    decision = _decision(intent, effect_attempt_limit=3)
    store.put_decision(decision)

    first = store.acquire_attempt(
        decision,
        owner_id="owner-1",
        lease_id="lease-1",
    )
    assert (
        store.acquire_attempt(
            decision,
            owner_id="owner-1",
            lease_id="lease-1",
        )
        == first
    )
    with pytest.raises(HarnessValidationError) as active:
        store.acquire_attempt(decision, owner_id="owner-2", lease_id="lease-2")
    assert active.value.code == "side_effect_attempt_in_progress"

    clock.advance(31)
    with pytest.raises(HarnessValidationError) as expired:
        store.acquire_attempt(decision, owner_id="owner-2", lease_id="lease-2")
    assert expired.value.code == "side_effect_attempt_termination_unconfirmed"
    indeterminate = store.finish_attempt(first, termination_confirmed=False)
    assert indeterminate.status is HarnessSideEffectAttemptStatus.INDETERMINATE
    with pytest.raises(HarnessValidationError) as unresolved:
        store.acquire_attempt(decision, owner_id="owner-2", lease_id="lease-2")
    assert unresolved.value.code == "side_effect_attempt_termination_unconfirmed"

    store.finish_attempt(first, termination_confirmed=True)
    second = store.acquire_attempt(
        decision,
        owner_id="owner-2",
        lease_id="lease-2",
    )
    assert second.attempt == second.fencing_generation == 2
    assert second.idempotency_key == first.idempotency_key
    with pytest.raises(HarnessValidationError) as stale:
        store.complete_attempt(first, _outcome(decision))
    assert stale.value.code == "stale_side_effect_attempt"

    committed = store.complete_attempt(second, _outcome(decision))
    assert committed.attempt_id == second.attempt_id
    assert committed.fencing_generation == second.fencing_generation
    assert committed.schema_version == "newsroom.harness-side-effect-outcome/v2"
    assert HarnessSideEffectOutcome.from_dict(committed.to_dict()) == committed
    completed_attempt = store.get_attempt(
        effect_id=decision.effect_id,
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert completed_attempt.status is HarnessSideEffectAttemptStatus.TERMINATED
    assert completed_attempt.outcome_ref == committed.checksum
    quarantined = store.set_disposition(
        effect_id=decision.effect_id,
        disposition="quarantine",
        identity_scope_ref=decision.identity_scope_ref,
        subject_scope_ref=decision.subject_scope_ref,
    )
    assert quarantined is not None
    assert (
        store.get_attempt(
            effect_id=decision.effect_id,
            identity_scope_ref=decision.identity_scope_ref,
            subject_scope_ref=decision.subject_scope_ref,
        ).outcome_ref
        == quarantined.checksum
    )
    with pytest.raises(HarnessValidationError) as bypass:
        store.put_outcome(_outcome(decision))
    assert bypass.value.code == "fenced_side_effect_attempt_required"


def test_side_effect_outcome_schema_registry_covers_both_write_paths() -> None:
    evidence = json.loads(
        Path(
            "openspec/changes/harness-workflow-graph-runtime/evidence/"
            "schema-version-registry.json"
        ).read_text(encoding="utf-8")
    )
    retained = evidence["retained_dependency_versions"]
    assert retained["side_effect_outcome"] == (
        "newsroom.harness-side-effect-outcome/v1"
    )
    assert retained["fenced_side_effect_outcome"] == (
        "newsroom.harness-side-effect-outcome/v2"
    )
    policy = evidence["side_effect_outcome_version_policy"]
    assert policy["reader_dispatch"].startswith("exact schema identity")
    assert [item["schema"] for item in policy["writers"]] == [
        "newsroom.harness-side-effect-outcome/v1",
        "newsroom.harness-side-effect-outcome/v2",
    ]
    assert policy["upcasters"] == []
    assert policy["v1_to_v2_upcast_allowed"] is False
    assert policy["compatibility_window"]["same_outcome_dual_write"] is False


def test_in_memory_fenced_attempt_acquisition_is_atomic() -> None:
    store = InMemoryHarnessSideEffectStore()
    intent = _intent(effect_id="effect-concurrent-fenced")
    decision = _decision(intent, effect_attempt_limit=4)
    store.put_decision(decision)

    def acquire(index: int) -> int | str:
        try:
            return store.acquire_attempt(
                decision,
                owner_id=f"owner-{index}",
                lease_id=f"lease-{index}",
            ).attempt
        except HarnessValidationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(acquire, range(4)))

    assert results.count(1) == 1
    assert results.count("side_effect_attempt_in_progress") == 3


def test_store_and_handler_commit_once_and_enforce_scope() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    intent = _intent()
    decision = _decision(intent)
    store.put_decision(decision)
    first = handler.commit(intent, decision)
    second = handler.commit(intent, decision)
    assert first == second
    assert HarnessSideEffectDecision.from_dict(decision.to_dict()) == decision
    assert HarnessSideEffectOutcome.from_dict(first.to_dict()) == first
    assert first.schema_version == "newsroom.harness-side-effect-outcome/v1"
    assert "attempt_id" not in first.to_dict()
    assert "fencing_generation" not in first.to_dict()
    assert handler.effect_count == 1
    assert store.outcome_write_count == 1
    with pytest.raises(HarnessValidationError, match="scope mismatch"):
        store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=checksum_for({"tenant_id": "tenant-other"}),
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )


def test_approval_resolver_requires_exact_effect_identity() -> None:
    request = HarnessSideEffectApprovalRequest(
        run_id="run-1",
        step_id="publish_artifacts",
        attempt=1,
        effect_id="effect-1",
        candidate_checksum=checksum_for({"candidate": 1}),
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
        decision_version="1",
    )
    evidence = HarnessSideEffectApprovalEvidence(
        approval_ref=checksum_for({"approval": 1}),
        **request.to_dict(),
    )
    resolver = InMemoryHarnessSideEffectApprovalResolver((evidence,))
    assert resolver.resolve(request, approval_ref=evidence.approval_ref) == evidence
    with pytest.raises(HarnessValidationError) as captured:
        resolver.resolve(
            HarnessSideEffectApprovalRequest(
                **{**request.to_dict(), "effect_id": "effect-other"}
            ),
            approval_ref=evidence.approval_ref,
        )
    assert captured.value.code == "side_effect_approval_mismatch"


def test_terminal_policy_requires_pinned_no_approval_evidence() -> None:
    policy = HarnessTerminalSideEffectPolicy(
        policy_id="research-terminal",
        version="1",
        handler="research.terminal@1",
        kind="artifact",
        requires_approval=False,
        retry_limit=2,
        not_required_evidence_ref=checksum_for({"policy": "not_required"}),
    )
    assert HarnessTerminalSideEffectPolicy.from_dict(policy.to_dict()) == policy
    with pytest.raises(HarnessValidationError, match="not_required"):
        HarnessTerminalSideEffectPolicy(
            policy_id="research-terminal",
            version="1",
            handler="research.terminal@1",
            kind="artifact",
            requires_approval=False,
            retry_limit=2,
        )


def test_optional_step_and_terminal_side_effect_serialization_is_omission_compatible() -> (
    None
):
    plain_step = HarnessStepSpec(step_id="plain", worker_type="script")
    declared_step = HarnessStepSpec(
        step_id="publish",
        worker_type="artifact",
        side_effect_handler="research.artifact@1",
    )
    assert "side_effect_handler" not in plain_step.to_dict()
    assert declared_step.to_dict()["side_effect_handler"] == {
        "handler_id": "research.artifact",
        "version": "1",
    }

    legacy = HarnessWorkflowSpec(
        workflow_id="legacy",
        steps=(plain_step,),
        entry_step_id="plain",
    )
    assert legacy.to_dict()["terminal_policies"] == {}
    policy = HarnessTerminalSideEffectPolicy(
        policy_id="research-terminal",
        version="1",
        handler="research.terminal@1",
        kind="artifact",
        requires_approval=False,
        retry_limit=2,
        not_required_evidence_ref=checksum_for({"policy": "not_required"}),
    )
    declared = HarnessWorkflowSpec(
        workflow_id="declared",
        steps=(declared_step,),
        entry_step_id="publish",
        terminal_side_effect_policy=policy,
    )
    assert declared.terminal_side_effect_policy == policy
    assert declared.to_dict()["terminal_policies"]["side_effect"] == policy.to_dict()
