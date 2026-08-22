from __future__ import annotations

import pytest
from dataclasses import replace

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.fake import (
    CountingHarnessSideEffectHandler,
    InMemoryHarnessSideEffectStore,
)
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
)


GRAPH_CHECKSUM = checksum_for({"graph": "side-effect-identity"})
IDENTITY_SCOPE = checksum_for({"tenant": "tenant-1"})
SUBJECT_SCOPE = checksum_for({"subject": "subject-1"})


def _intent(node_instance_id: str) -> HarnessSideEffectIntent:
    effect_id = "shared-effect-id"
    return HarnessSideEffectIntent(
        effect_id=effect_id,
        kind="artifact",
        run_id="run-side-effect-identity",
        graph_id="research.graph",
        graph_version="1",
        graph_ref="research.graph@1",
        graph_checksum=GRAPH_CHECKSUM,
        origin=HarnessSideEffectOrigin.WORKER,
        atomic_group="shared-effect-group",
        identity_scope_ref=IDENTITY_SCOPE,
        subject_scope_ref=SUBJECT_SCOPE,
        node_id="publish",
        node_instance_id=node_instance_id,
        activity_id=f"activity:{node_instance_id}",
        step_id="publish_artifacts",
        worker_result_ref=checksum_for({"worker": node_instance_id}),
        candidate_checksum=checksum_for({"candidate": node_instance_id}),
        handler="research.artifact@1",
        candidate_refs=(f"candidate://{node_instance_id}",),
    )


def _decision(intent: HarnessSideEffectIntent) -> HarnessSideEffectDecision:
    return HarnessSideEffectDecision(
        decision_id=f"decision:{intent.node_instance_id}",
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
        command_ordinal=1,
        causation_id=f"event:{intent.node_instance_id}",
        disposition="prepared",
        node_id=intent.node_id,
        node_instance_id=intent.node_instance_id,
        activity_id=intent.activity_id,
        step_id=intent.step_id,
        attempt=intent.attempt,
        worker_result_ref=intent.worker_result_ref,
        approval_evidence_ref=checksum_for({"approval": intent.node_instance_id}),
    )


def test_same_effect_id_different_node_instances_are_independently_idempotent() -> None:
    store = InMemoryHarnessSideEffectStore()
    handler = CountingHarnessSideEffectHandler(store)
    left_intent = _intent("publish:1")
    right_intent = _intent("publish:2")
    left_decision = _decision(left_intent)
    right_decision = _decision(right_intent)

    store.put_decision(left_decision)
    store.put_decision(right_decision)
    left_outcome = handler.commit(left_intent, left_decision)
    right_outcome = handler.commit(right_intent, right_decision)

    assert left_outcome.node_instance_id == "publish:1"
    assert right_outcome.node_instance_id == "publish:2"
    assert left_outcome != right_outcome
    assert len(store.outcomes_by_identity) == 2
    assert (
        store.get_outcome(
            effect_id=left_intent.effect_id,
            identity_scope_ref=left_intent.identity_scope_ref,
            subject_scope_ref=left_intent.subject_scope_ref,
            idempotency_key=left_intent.idempotency_key,
        )
        == left_outcome
    )
    with pytest.raises(HarnessValidationError, match="ambiguous"):
        store.read_outcome(
            effect_id=left_intent.effect_id,
            identity_scope_ref=left_intent.identity_scope_ref,
            subject_scope_ref=left_intent.subject_scope_ref,
        )


def test_authorization_cannot_drop_worker_physical_identity() -> None:
    intent = _intent("publish:1")
    decision = _decision(intent)
    with pytest.raises(HarnessValidationError, match="authorization does not match"):
        CountingHarnessSideEffectHandler(InMemoryHarnessSideEffectStore()).commit(
            intent,
            replace(decision, node_instance_id="publish:other", checksum=None),
        )


def test_same_effect_id_different_node_instances_have_independent_attempt_fences() -> None:
    store = InMemoryHarnessSideEffectStore()
    left_decision = _decision(_intent("publish:1"))
    right_decision = _decision(_intent("publish:2"))
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


def test_effect_only_reads_fail_closed_for_scope_and_parallel_identity() -> None:
    store = InMemoryHarnessSideEffectStore()
    left_intent = _intent("publish:1")
    right_intent = _intent("publish:2")
    left_decision = _decision(left_intent)
    right_decision = _decision(right_intent)
    store.put_decision(left_decision)
    store.put_decision(right_decision)
    handler = CountingHarnessSideEffectHandler(store)
    handler.commit(left_intent, left_decision)
    handler.commit(right_intent, right_decision)

    with pytest.raises(HarnessValidationError, match="scope mismatch"):
        store.read_outcome(
            effect_id=left_intent.effect_id,
            identity_scope_ref=checksum_for({"scope": "other"}),
            subject_scope_ref=left_intent.subject_scope_ref,
        )
    with pytest.raises(HarnessValidationError, match="ambiguous"):
        store.attempt_count(
            effect_id=left_intent.effect_id,
            identity_scope_ref=left_intent.identity_scope_ref,
            subject_scope_ref=left_intent.subject_scope_ref,
        )
