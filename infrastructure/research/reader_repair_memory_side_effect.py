"""Harness-owned preparation and terminal commit for Reader Repair memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessSideEffectDecision,
    HarnessSideEffectDecisionStatus,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
    HarnessSideEffectStorePort,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.memory import MemoryWriteCandidate
from framework.shared.time import utc_now

from backend.research.ports.repair_memory import (
    READER_REPAIR_MEMORY_EFFECT_KIND,
    READER_REPAIR_MEMORY_HANDLER_REF,
    READER_REPAIR_MEMORY_SCHEMA_VERSION,
    ReaderRepairMemoryCandidateProjection,
    ReaderRepairMemoryCommitPort,
    ReaderRepairMemoryCommitReceipt,
    ReaderRepairMemoryCommitRequest,
    reader_repair_case_memory_ref,
    reader_repair_strategy_memory_ref,
    validate_reader_repair_memory_candidate,
)


_MEMORY_GATE_REF = "ReaderRepairMemoryPolicyGate@1"


class ReaderRepairMemorySideEffectHandler:
    """Prepare a hidden candidate and atomically commit it at run completion.

    Production composition registers the handler only when it can provide the
    durable Reader Repair memory ports. Its commit port is a stricter boundary
    than the legacy per-object ``ReaderRepairMemoryPort`` and must supply
    atomic idempotency itself.
    """

    def __init__(
        self,
        *,
        commit_port: ReaderRepairMemoryCommitPort,
        side_effect_store: HarnessSideEffectStorePort,
    ) -> None:
        if not isinstance(commit_port, ReaderRepairMemoryCommitPort):
            raise TypeError(
                "ReaderRepairMemorySideEffectHandler requires "
                "ReaderRepairMemoryCommitPort"
            )
        if not isinstance(side_effect_store, HarnessSideEffectStorePort):
            raise TypeError(
                "ReaderRepairMemorySideEffectHandler requires "
                "HarnessSideEffectStorePort"
            )
        self.commit_port = commit_port
        self.side_effect_store = side_effect_store
        self.prepare_calls = 0
        self.commit_calls = 0

    def prepare(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.prepare_calls += 1
        _assert_worker_authority(intent, authorization)
        projection = _projection_from_worker_intent(intent)
        existing = self._existing_outcome(intent, authorization)
        if existing is not None:
            _verify_prepared_outcome(intent, authorization, existing, projection)
            return existing
        now = utc_now()
        return HarnessSideEffectOutcome(
            outcome_id=(
                "reader-repair-memory-prepared:"
                f"{_identity_digest(intent.effect_id, projection.candidate_checksum)}"
            ),
            effect_id=intent.effect_id,
            decision_ref=authorization.checksum,
            run_id=intent.run_id,
            graph_id=intent.graph_id,
            graph_version=intent.graph_version,
            graph_ref=intent.graph_ref,
            graph_checksum=intent.graph_checksum,
            origin=intent.origin,
            kind=intent.kind,
            handler=authorization.handler,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=HarnessSideEffectDisposition.PREPARED,
            node_id=intent.node_id,
            node_instance_id=intent.node_instance_id,
            activity_id=intent.activity_id,
            terminal_action=intent.terminal_action,
            attempt=intent.attempt,
            candidate_refs=intent.candidate_refs,
            result_ref=projection.candidate_checksum,
            reason_code="memory_candidate_prepared",
            committed_at=now,
            metadata={
                "schema_version": READER_REPAIR_MEMORY_SCHEMA_VERSION,
                "memory_write_candidate": projection.candidate.to_dict(),
                "memory_candidate_checksum": projection.candidate_checksum,
                "worker_intent_ref": intent.checksum,
            },
        )

    def commit(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        self.commit_calls += 1
        _assert_terminal_authority(intent, authorization)
        prepared = self._prepared_outcome(intent)
        projection = _projection_from_prepared(prepared)
        existing = self._existing_outcome(intent, authorization)
        if existing is not None:
            _verify_terminal_outcome(intent, authorization, existing, prepared, projection)
            return existing

        request = _commit_request(intent, authorization, prepared, projection)
        receipt = self.commit_port.commit(request)
        _verify_commit_receipt(request, receipt)
        assert receipt.checksum is not None
        return HarnessSideEffectOutcome(
            outcome_id=(
                "reader-repair-memory-committed:"
                f"{_identity_digest(request.checksum, receipt.checksum)}"
            ),
            effect_id=intent.effect_id,
            decision_ref=authorization.checksum,
            run_id=intent.run_id,
            graph_id=intent.graph_id,
            graph_version=intent.graph_version,
            graph_ref=intent.graph_ref,
            graph_checksum=intent.graph_checksum,
            origin=intent.origin,
            kind=intent.kind,
            handler=authorization.handler,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=HarnessSideEffectDisposition.ACCEPTED,
            node_id=intent.node_id,
            node_instance_id=intent.node_instance_id,
            activity_id=intent.activity_id,
            terminal_action=intent.terminal_action,
            attempt=intent.attempt,
            candidate_refs=intent.candidate_refs,
            public_refs=receipt.public_refs,
            result_ref=receipt.checksum,
            reason_code="memory_bundle_committed",
            committed_at=receipt.committed_at,
            metadata={
                "schema_version": READER_REPAIR_MEMORY_SCHEMA_VERSION,
                "prepared_outcome_ref": prepared.checksum,
                "memory_candidate_checksum": projection.candidate_checksum,
                "commit_request_ref": request.checksum,
                "commit_receipt": receipt.to_dict(),
            },
        )

    def _prepared_outcome(
        self,
        intent: HarnessSideEffectIntent,
    ) -> HarnessSideEffectOutcome:
        raw_refs = intent.payload.get("prepared_outcome_refs")
        if isinstance(raw_refs, str | bytes) or not isinstance(raw_refs, Sequence):
            raise _error(
                "reader_repair_prepared_outcome_invalid",
                "Reader Repair terminal intent requires prepared_outcome_refs",
            )
        refs = tuple(raw_refs)
        if len(refs) != 1 or not isinstance(refs[0], str):
            raise _error(
                "reader_repair_prepared_outcome_invalid",
                "Reader Repair terminal intent requires exactly one prepared outcome",
            )
        wanted = refs[0]
        matches: list[HarnessSideEffectOutcome] = []
        for decision in self.side_effect_store.list_decisions(run_id=intent.run_id):
            if (
                decision.origin is not HarnessSideEffectOrigin.WORKER
                or decision.kind != READER_REPAIR_MEMORY_EFFECT_KIND
                or str(decision.handler) != READER_REPAIR_MEMORY_HANDLER_REF
                or decision.identity_scope_ref != intent.identity_scope_ref
                or decision.subject_scope_ref != intent.subject_scope_ref
            ):
                continue
            outcome = self.side_effect_store.get_outcome(
                effect_id=decision.effect_id,
                identity_scope_ref=decision.identity_scope_ref,
                subject_scope_ref=decision.subject_scope_ref,
                idempotency_key=decision.idempotency_key,
            )
            if outcome is not None and outcome.checksum == wanted:
                if (
                    decision.disposition is not HarnessSideEffectDisposition.PREPARED
                    or decision.status
                    is not HarnessSideEffectDecisionStatus.AUTHORIZED
                    or _MEMORY_GATE_REF not in decision.gate_refs
                    or outcome.decision_ref != decision.checksum
                    or outcome.run_id != decision.run_id
                    or outcome.kind != decision.kind
                    or outcome.handler != decision.handler
                    or outcome.identity_scope_ref != decision.identity_scope_ref
                    or outcome.subject_scope_ref != decision.subject_scope_ref
                    or outcome.atomic_group != decision.atomic_group
                    or outcome.idempotency_key != decision.idempotency_key
                    or outcome.metadata.get("worker_intent_ref")
                    != decision.intent_ref
                ):
                    raise _error(
                        "reader_repair_prepared_outcome_conflict",
                        "Reader Repair prepared outcome lacks exact durable authority",
                    )
                matches.append(outcome)
        if len(matches) != 1:
            raise _error(
                "reader_repair_prepared_outcome_missing",
                "Reader Repair terminal commit has no exact prepared outcome",
            )
        prepared = matches[0]
        if (
            prepared.disposition is not HarnessSideEffectDisposition.PREPARED
            or prepared.atomic_group != intent.atomic_group
            or prepared.run_id != intent.run_id
            or prepared.kind != intent.kind
            or str(prepared.handler) != READER_REPAIR_MEMORY_HANDLER_REF
            or tuple(intent.candidate_refs) != tuple(prepared.candidate_refs)
        ):
            raise _error(
                "reader_repair_prepared_outcome_conflict",
                "Reader Repair prepared outcome conflicts with terminal authority",
            )
        return prepared

    def _existing_outcome(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome | None:
        existing = self.side_effect_store.get_outcome(
            effect_id=intent.effect_id,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            idempotency_key=intent.idempotency_key,
        )
        if existing is None:
            return None
        if (
            existing.decision_ref != authorization.checksum
            or existing.run_id != intent.run_id
            or existing.kind != intent.kind
            or existing.handler != authorization.handler
            or existing.atomic_group != intent.atomic_group
            or existing.identity_scope_ref != intent.identity_scope_ref
            or existing.subject_scope_ref != intent.subject_scope_ref
            or existing.idempotency_key != intent.idempotency_key
        ):
            raise _error(
                "reader_repair_existing_outcome_conflict",
                "existing Reader Repair memory outcome conflicts with authority",
            )
        return existing


def _projection_from_worker_intent(
    intent: HarnessSideEffectIntent,
) -> ReaderRepairMemoryCandidateProjection:
    if intent.kind != READER_REPAIR_MEMORY_EFFECT_KIND:
        raise _error(
            "reader_repair_memory_kind_invalid",
            "Reader Repair memory intent kind is invalid",
        )
    if str(intent.handler) != READER_REPAIR_MEMORY_HANDLER_REF:
        raise _error(
            "reader_repair_memory_handler_invalid",
            "Reader Repair memory intent handler is invalid",
        )
    if set(intent.payload) != {
        "schema_version",
        "memory_write_candidate",
        "memory_candidate_checksum",
    }:
        raise _error(
            "reader_repair_memory_payload_invalid",
            "Reader Repair memory intent payload fields are invalid",
        )
    if intent.payload.get("schema_version") != READER_REPAIR_MEMORY_SCHEMA_VERSION:
        raise _error(
            "reader_repair_memory_schema_invalid",
            "Reader Repair memory intent schema is invalid",
        )
    raw_candidate = intent.payload.get("memory_write_candidate")
    if not isinstance(raw_candidate, Mapping) or set(raw_candidate) != {
        "candidate_id",
        "namespace",
        "content",
        "source_refs",
        "status",
        "metadata",
    }:
        raise _error(
            "reader_repair_memory_candidate_invalid",
            "Reader Repair memory candidate fields are invalid",
        )
    try:
        candidate = MemoryWriteCandidate(
            candidate_id=raw_candidate["candidate_id"],
            namespace=raw_candidate["namespace"],
            content=dict(raw_candidate["content"]),
            source_refs=tuple(raw_candidate["source_refs"]),
            status=raw_candidate["status"],
            metadata=dict(raw_candidate["metadata"]),
        )
        projection = validate_reader_repair_memory_candidate(candidate)
    except (TypeError, ValueError) as exc:
        raise _error(
            "reader_repair_memory_candidate_invalid",
            "Reader Repair memory candidate failed validation",
            error_type=type(exc).__name__,
        ) from exc
    if intent.payload.get("memory_candidate_checksum") != projection.candidate_checksum:
        raise _error(
            "reader_repair_memory_candidate_checksum_mismatch",
            "Reader Repair memory candidate checksum does not match its payload",
        )
    expected_ref = (
        f"memory-candidate://{projection.candidate.namespace}/"
        f"{projection.candidate.candidate_id}"
    )
    if tuple(intent.candidate_refs) != (expected_ref,):
        raise _error(
            "reader_repair_memory_candidate_ref_mismatch",
            "Reader Repair memory candidate ref does not match its payload",
        )
    expected_bound_checksum = checksum_for(
        {
            "worker_result_ref": intent.worker_result_ref,
            "payload": intent.payload,
            "candidate_refs": intent.candidate_refs,
            "atomic_group": intent.atomic_group,
        }
    )
    if intent.candidate_checksum != expected_bound_checksum:
        raise _error(
            "reader_repair_memory_worker_binding_mismatch",
            "Reader Repair memory intent is not bound to its worker result",
        )
    return projection


def _projection_from_prepared(
    prepared: HarnessSideEffectOutcome,
) -> ReaderRepairMemoryCandidateProjection:
    if prepared.metadata.get("schema_version") != READER_REPAIR_MEMORY_SCHEMA_VERSION:
        raise _error(
            "reader_repair_prepared_outcome_invalid",
            "prepared Reader Repair memory outcome schema is invalid",
        )
    raw_candidate = prepared.metadata.get("memory_write_candidate")
    if not isinstance(raw_candidate, Mapping):
        raise _error(
            "reader_repair_prepared_outcome_invalid",
            "prepared Reader Repair memory outcome has no candidate",
        )
    try:
        candidate = MemoryWriteCandidate(
            candidate_id=raw_candidate["candidate_id"],
            namespace=raw_candidate["namespace"],
            content=dict(raw_candidate["content"]),
            source_refs=tuple(raw_candidate["source_refs"]),
            status=raw_candidate["status"],
            metadata=dict(raw_candidate["metadata"]),
        )
        projection = validate_reader_repair_memory_candidate(candidate)
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(
            "reader_repair_prepared_outcome_invalid",
            "prepared Reader Repair memory candidate is invalid",
            error_type=type(exc).__name__,
        ) from exc
    if (
        prepared.result_ref != projection.candidate_checksum
        or prepared.metadata.get("memory_candidate_checksum")
        != projection.candidate_checksum
    ):
        raise _error(
            "reader_repair_prepared_outcome_checksum_mismatch",
            "prepared Reader Repair memory candidate checksum does not match",
        )
    return projection


def _commit_request(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
    prepared: HarnessSideEffectOutcome,
    projection: ReaderRepairMemoryCandidateProjection,
) -> ReaderRepairMemoryCommitRequest:
    assert authorization.checksum is not None
    assert prepared.checksum is not None
    digest = _identity_digest(
        intent.checksum,
        authorization.checksum,
        prepared.checksum,
        projection.candidate_checksum,
    )
    return ReaderRepairMemoryCommitRequest(
        request_id=f"reader-repair-memory-commit:{digest}",
        run_id=intent.run_id,
        terminal_effect_id=intent.effect_id,
        candidate=projection.candidate,
        candidate_checksum=projection.candidate_checksum,
        prepared_outcome_ref=prepared.checksum,
        authorization_ref=authorization.checksum,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
    )


def _verify_commit_receipt(
    request: ReaderRepairMemoryCommitRequest,
    receipt: ReaderRepairMemoryCommitReceipt,
) -> None:
    if not isinstance(receipt, ReaderRepairMemoryCommitReceipt):
        raise _error(
            "reader_repair_memory_receipt_invalid",
            "Reader Repair memory adapter returned an invalid receipt",
        )
    projection = request.projection
    expected_strategy_refs = tuple(
        reader_repair_strategy_memory_ref(strategy, version=version)
        for strategy, version in zip(
            projection.strategies,
            receipt.strategy_versions,
            strict=True,
        )
    )
    if (
        receipt.request_ref != request.checksum
        or receipt.run_id != request.run_id
        or receipt.terminal_effect_id != request.terminal_effect_id
        or receipt.authorization_ref != request.authorization_ref
        or receipt.idempotency_key != request.idempotency_key
        or receipt.namespace != projection.candidate.namespace
        or receipt.case_ref
        != reader_repair_case_memory_ref(
            projection.repair_case,
            version=receipt.case_version,
        )
        or receipt.strategy_refs != expected_strategy_refs
        or receipt.checksum is None
    ):
        raise _error(
            "reader_repair_memory_receipt_conflict",
            "Reader Repair memory receipt conflicts with the terminal request",
        )


def _verify_prepared_outcome(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
    outcome: HarnessSideEffectOutcome,
    projection: ReaderRepairMemoryCandidateProjection,
) -> None:
    if (
        outcome.disposition is not HarnessSideEffectDisposition.PREPARED
        or outcome.result_ref != projection.candidate_checksum
        or tuple(outcome.candidate_refs) != tuple(intent.candidate_refs)
        or outcome.metadata.get("worker_intent_ref") != intent.checksum
        or outcome.metadata.get("memory_candidate_checksum")
        != projection.candidate_checksum
        or outcome.decision_ref != authorization.checksum
    ):
        raise _error(
            "reader_repair_prepared_outcome_conflict",
            "existing Reader Repair prepared outcome conflicts with the candidate",
        )
    _projection_from_prepared(outcome)


def _verify_terminal_outcome(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
    outcome: HarnessSideEffectOutcome,
    prepared: HarnessSideEffectOutcome,
    projection: ReaderRepairMemoryCandidateProjection,
) -> None:
    request = _commit_request(intent, authorization, prepared, projection)
    raw_receipt = outcome.metadata.get("commit_receipt")
    if not isinstance(raw_receipt, Mapping):
        raise _error(
            "reader_repair_terminal_outcome_conflict",
            "existing Reader Repair terminal outcome has no commit receipt",
        )
    try:
        receipt = ReaderRepairMemoryCommitReceipt.from_dict(raw_receipt)
        _verify_commit_receipt(request, receipt)
    except (TypeError, ValueError, HarnessValidationError) as exc:
        raise _error(
            "reader_repair_terminal_outcome_conflict",
            "existing Reader Repair terminal receipt is invalid",
            error_type=type(exc).__name__,
        ) from exc
    if (
        outcome.disposition is not HarnessSideEffectDisposition.ACCEPTED
        or outcome.decision_ref != authorization.checksum
        or outcome.metadata.get("prepared_outcome_ref") != prepared.checksum
        or outcome.metadata.get("memory_candidate_checksum")
        != projection.candidate_checksum
        or outcome.metadata.get("commit_request_ref") != request.checksum
        or tuple(outcome.candidate_refs) != tuple(intent.candidate_refs)
        or tuple(outcome.public_refs) != receipt.public_refs
        or outcome.result_ref != receipt.checksum
        or outcome.committed_at != receipt.committed_at
    ):
        raise _error(
            "reader_repair_terminal_outcome_conflict",
            "existing Reader Repair terminal outcome conflicts with authority",
        )


def _assert_worker_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if (
        intent.origin is not HarnessSideEffectOrigin.WORKER
        or authorization.disposition is not HarnessSideEffectDisposition.PREPARED
        or authorization.worker_result_ref != intent.worker_result_ref
        or authorization.node_id != intent.node_id
        or authorization.node_instance_id != intent.node_instance_id
        or authorization.activity_id != intent.activity_id
    ):
        raise _error(
            "reader_repair_memory_worker_authority_invalid",
            "Reader Repair preparation requires exact worker authority",
        )
    _assert_common_authority(intent, authorization)


def _assert_terminal_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if (
        intent.origin is not HarnessSideEffectOrigin.CONTROLLER_TERMINAL
        or intent.terminal_action != "complete_run"
        or authorization.disposition is not HarnessSideEffectDisposition.ACCEPTED
        or authorization.terminal_action != intent.terminal_action
        or authorization.terminal_state_ref != intent.state_checksum
    ):
        raise _error(
            "reader_repair_memory_terminal_authority_invalid",
            "Reader Repair commit requires controller-terminal authority",
        )
    _assert_common_authority(intent, authorization)


def _assert_common_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> None:
    if (
        authorization.status is not HarnessSideEffectDecisionStatus.AUTHORIZED
        or authorization.effect_id != intent.effect_id
        or authorization.intent_ref != intent.checksum
        or authorization.run_id != intent.run_id
        or authorization.graph_id != intent.graph_id
        or authorization.graph_version != intent.graph_version
        or authorization.graph_ref != intent.graph_ref
        or authorization.graph_checksum != intent.graph_checksum
        or authorization.kind != READER_REPAIR_MEMORY_EFFECT_KIND
        or intent.kind != READER_REPAIR_MEMORY_EFFECT_KIND
        or str(authorization.handler) != READER_REPAIR_MEMORY_HANDLER_REF
        or str(intent.handler) != READER_REPAIR_MEMORY_HANDLER_REF
        or authorization.identity_scope_ref != intent.identity_scope_ref
        or authorization.subject_scope_ref != intent.subject_scope_ref
        or authorization.atomic_group != intent.atomic_group
        or authorization.idempotency_key != intent.idempotency_key
        or authorization.attempt != intent.attempt
        or _MEMORY_GATE_REF not in authorization.gate_refs
    ):
        raise _error(
            "reader_repair_memory_authority_mismatch",
            "Reader Repair memory authority does not match its intent",
        )


def _identity_digest(*values: Any) -> str:
    return checksum_for(list(values)).removeprefix("sha256:")


def _error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


__all__ = ["ReaderRepairMemorySideEffectHandler"]
