from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.side_effects.models import (
    HarnessSideEffectDecision,
    HarnessSideEffectDecisionStatus,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessSideEffectOutcome,
)

from business.research.ports.reader_repair_failure_diagnostic import (
    READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND,
    READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
    READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION,
    ReaderRepairFailureDiagnosticCandidate,
    ReaderRepairFailureDiagnosticCommitPort,
    ReaderRepairFailureDiagnosticCommitReceipt,
    ReaderRepairFailureDiagnosticCommitRequest,
)


class ReaderRepairFailureDiagnosticSideEffectHandler:
    """Commits one quarantined diagnostic case after durable Graph failure."""

    def __init__(
        self,
        commit_port: ReaderRepairFailureDiagnosticCommitPort,
    ) -> None:
        if not isinstance(commit_port, ReaderRepairFailureDiagnosticCommitPort):
            raise TypeError(
                "commit_port must implement ReaderRepairFailureDiagnosticCommitPort"
            )
        self._commit_port = commit_port

    def commit(
        self,
        intent: HarnessSideEffectIntent,
        authorization: HarnessSideEffectDecision,
    ) -> HarnessSideEffectOutcome:
        candidate = _validate_authority(intent, authorization)
        candidate_ref = _candidate_checksum(candidate)
        record_ref = _record_checksum(candidate)
        request = ReaderRepairFailureDiagnosticCommitRequest(
            request_id=(
                "reader-repair-failure-diagnostic-request:"
                f"{_identity_digest(intent.effect_id, authorization.checksum, candidate_ref)}"
            ),
            run_id=intent.run_id,
            terminal_effect_id=intent.effect_id,
            candidate=candidate,
            candidate_checksum=candidate_ref,
            authorization_ref=_authorization_checksum(authorization),
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            idempotency_key=intent.idempotency_key,
        )
        receipt = self._commit_port.commit_failure_diagnostic(request)
        _verify_receipt(request, receipt)
        if receipt.checksum is None:  # pragma: no cover - model invariant
            raise AssertionError("failure diagnostic receipt checksum is missing")
        return HarnessSideEffectOutcome(
            outcome_id=(
                "reader-repair-failure-diagnostic-outcome:"
                f"{_identity_digest(intent.effect_id, authorization.checksum)}"
            ),
            effect_id=intent.effect_id,
            decision_ref=_authorization_checksum(authorization),
            run_id=intent.run_id,
            graph_id=intent.graph_id,
            graph_version=intent.graph_version,
            graph_ref=intent.graph_ref,
            graph_checksum=intent.graph_checksum,
            origin=intent.origin,
            kind=intent.kind,
            handler=READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
            idempotency_key=intent.idempotency_key,
            identity_scope_ref=intent.identity_scope_ref,
            subject_scope_ref=intent.subject_scope_ref,
            atomic_group=intent.atomic_group,
            disposition=HarnessSideEffectDisposition.QUARANTINE,
            node_id=intent.node_id,
            node_instance_id=intent.node_instance_id,
            activity_id=intent.activity_id,
            terminal_action=intent.terminal_action,
            attempt=intent.attempt,
            candidate_refs=tuple(intent.candidate_refs),
            public_refs=(),
            result_ref=receipt.checksum,
            reason_code="failure_diagnostic_committed",
            committed_at=receipt.committed_at,
            retention_until=intent.retention_until,
            metadata={
                "failure_diagnostic_receipt": receipt.to_dict(),
                "terminal_failure_record_ref": record_ref,
                "failed_gate_evidence_refs": list(
                    candidate.failed_gate_evidence_refs
                ),
            },
        )


def _validate_authority(
    intent: HarnessSideEffectIntent,
    authorization: HarnessSideEffectDecision,
) -> ReaderRepairFailureDiagnosticCandidate:
    if not isinstance(intent, HarnessSideEffectIntent):
        raise TypeError("intent must be HarnessSideEffectIntent")
    if not isinstance(authorization, HarnessSideEffectDecision):
        raise TypeError("authorization must be HarnessSideEffectDecision")
    if set(intent.payload) != {"failure_diagnostic_candidate"}:
        raise _error(
            "reader_repair_failure_diagnostic_payload_invalid",
            "Reader Repair failure diagnostic payload fields are invalid",
        )
    raw_candidate = intent.payload.get("failure_diagnostic_candidate")
    if not isinstance(raw_candidate, Mapping):
        raise _error(
            "reader_repair_failure_diagnostic_payload_invalid",
            "Reader Repair failure diagnostic candidate must be an object",
        )
    try:
        candidate = ReaderRepairFailureDiagnosticCandidate.from_dict(raw_candidate)
    except (TypeError, ValueError, HarnessValidationError) as exc:
        raise _error(
            "reader_repair_failure_diagnostic_candidate_invalid",
            "Reader Repair failure diagnostic candidate is invalid",
            error_type=type(exc).__name__,
        ) from exc
    candidate_ref = _candidate_checksum(candidate)
    record_ref = _record_checksum(candidate)
    expected_candidate_refs = (
        candidate_ref,
        record_ref,
        *candidate.failed_gate_evidence_refs,
    )
    if (
        intent.origin is not HarnessSideEffectOrigin.CONTROLLER_TERMINAL
        or intent.kind != READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND
        or str(intent.handler) != READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF
        or intent.terminal_action
        != READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION
        or intent.run_id != candidate.run_id
        or intent.state_checksum
        != candidate.terminal_failure.terminal_projection_ref
        or intent.completion_input_ref != record_ref
        or tuple(intent.candidate_refs) != expected_candidate_refs
        or intent.source_intent_ref is not None
    ):
        raise _error(
            "reader_repair_failure_diagnostic_intent_invalid",
            "Reader Repair failure diagnostic intent is not bound to terminal failure",
        )
    expected_gate_pairs = _failure_gate_pairs(candidate)
    if len(authorization.gate_refs) != len(authorization.gate_result_refs):
        raise _error(
            "reader_repair_failure_diagnostic_authority_mismatch",
            "Reader Repair failure diagnostic authority does not match its intent",
        )
    authorization_gate_pairs = tuple(
        zip(authorization.gate_refs, authorization.gate_result_refs)
    )
    if (
        authorization.status is not HarnessSideEffectDecisionStatus.AUTHORIZED
        or authorization.origin is not HarnessSideEffectOrigin.CONTROLLER_TERMINAL
        or authorization.disposition is not HarnessSideEffectDisposition.QUARANTINE
        or authorization.effect_id != intent.effect_id
        or authorization.intent_ref != intent.checksum
        or authorization.run_id != intent.run_id
        or authorization.kind != intent.kind
        or str(authorization.handler)
        != READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF
        or authorization.terminal_action != intent.terminal_action
        or authorization.terminal_state_ref != intent.state_checksum
        or authorization.identity_scope_ref != intent.identity_scope_ref
        or authorization.subject_scope_ref != intent.subject_scope_ref
        or authorization.atomic_group != intent.atomic_group
        or authorization.idempotency_key != intent.idempotency_key
        or authorization.attempt != intent.attempt
        or authorization.causation_id
        != candidate.terminal_failure.terminal_decision_ref
        or authorization_gate_pairs != expected_gate_pairs
        or authorization.aggregate_verdict_ref is None
        or authorization.approval_evidence_ref is None
        or authorization.budget_ref is None
    ):
        raise _error(
            "reader_repair_failure_diagnostic_authority_mismatch",
            "Reader Repair failure diagnostic authority does not match its intent",
        )
    return candidate


def _failure_gate_pairs(
    candidate: ReaderRepairFailureDiagnosticCandidate,
) -> tuple[tuple[str, str], ...]:
    selected = set(candidate.failed_gate_evidence_refs)
    pairs: set[tuple[str, str]] = set()
    for node in candidate.terminal_failure.failed_nodes:
        for evidence in node.gate_evidence:
            if evidence.evidence_ref not in selected:
                continue
            if evidence.contract_ref is None:
                raise _error(
                    "reader_repair_failure_diagnostic_gate_binding_missing",
                    "Reader Repair failed gate evidence lacks exact gate identity",
                    evidence_ref=evidence.evidence_ref,
                )
            pairs.add((evidence.contract_ref.exact_ref, evidence.evidence_ref))
    if len(pairs) != len(selected):
        raise _error(
            "reader_repair_failure_diagnostic_gate_binding_missing",
            "Reader Repair failed gate evidence cannot be resolved exactly",
        )
    return tuple(sorted(pairs))


def _verify_receipt(
    request: ReaderRepairFailureDiagnosticCommitRequest,
    receipt: ReaderRepairFailureDiagnosticCommitReceipt,
) -> None:
    if not isinstance(receipt, ReaderRepairFailureDiagnosticCommitReceipt):
        raise _error(
            "reader_repair_failure_diagnostic_receipt_invalid",
            "Reader Repair failure diagnostic port returned an invalid receipt",
        )
    record_ref = _record_checksum(request.candidate)
    if (
        receipt.request_ref != request.checksum
        or receipt.run_id != request.run_id
        or receipt.terminal_effect_id != request.terminal_effect_id
        or receipt.authorization_ref != request.authorization_ref
        or receipt.idempotency_key != request.idempotency_key
        or receipt.terminal_failure_record_ref != record_ref
        or receipt.public_refs
        or receipt.checksum is None
    ):
        raise _error(
            "reader_repair_failure_diagnostic_receipt_conflict",
            "Reader Repair failure diagnostic receipt conflicts with its request",
        )


def _candidate_checksum(candidate: ReaderRepairFailureDiagnosticCandidate) -> str:
    if candidate.checksum is None:  # pragma: no cover - model invariant
        raise AssertionError("failure diagnostic candidate checksum is missing")
    return candidate.checksum


def _record_checksum(candidate: ReaderRepairFailureDiagnosticCandidate) -> str:
    record_ref = candidate.terminal_failure.record_checksum
    if record_ref is None:  # pragma: no cover - model invariant
        raise AssertionError("terminal failure record checksum is missing")
    return record_ref


def _authorization_checksum(authorization: HarnessSideEffectDecision) -> str:
    if authorization.checksum is None:  # pragma: no cover - model invariant
        raise AssertionError("side-effect authorization checksum is missing")
    return authorization.checksum


def _identity_digest(*values: Any) -> str:
    return checksum_for(list(values)).removeprefix("sha256:")


def _error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code=code,
        details={"code": code, **details},
    )


__all__ = ["ReaderRepairFailureDiagnosticSideEffectHandler"]
