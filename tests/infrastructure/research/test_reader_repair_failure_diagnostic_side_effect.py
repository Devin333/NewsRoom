from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessControlPlane,
    HarnessGraphDecisionType,
    HarnessGraphTerminalFailureRecord,
    HarnessRunSpec,
    HarnessSideEffectDecision,
    HarnessSideEffectDisposition,
    HarnessSideEffectIntent,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerResult,
    InMemoryHarnessEventPort,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec

from business.research.domain import ReaderIssue, ReaderRepairCase, stable_research_id
from business.research.ports import (
    READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND,
    READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
    READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION,
    ReaderRepairFailureDiagnosticCandidate,
    ReaderRepairFailureDiagnosticCommitReceipt,
)
from infrastructure.research.reader_repair_failure_diagnostic_side_effect import (
    ReaderRepairFailureDiagnosticSideEffectHandler,
)
from infrastructure.storage.postgres.repair_memory_repository import (
    PostgresReaderRepairMemoryCommitRecord,
)
from interfaces.services.reader_repair_memory import (
    PostgresReaderRepairFailureDiagnosticCommitPort,
)


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
IDENTITY_SCOPE_REF = checksum_for({"tenant": "tenant-a", "user": "user-a"})
SUBJECT_SCOPE_REF = checksum_for({"paper_id": "paper-1"})


class _CommitPort:
    def __init__(self) -> None:
        self.calls = []

    def commit_failure_diagnostic(self, request):
        self.calls.append(request)
        record_ref = request.candidate.terminal_failure.record_checksum
        assert record_ref is not None
        return ReaderRepairFailureDiagnosticCommitReceipt(
            receipt_id=f"diagnostic-receipt:{request.request_id}",
            request_ref=request.checksum,
            run_id=request.run_id,
            terminal_effect_id=request.terminal_effect_id,
            authorization_ref=request.authorization_ref,
            idempotency_key=request.idempotency_key,
            namespace="research.reader_repair",
            diagnostic_case_ref=(
                "memory://research.reader_repair/case/repair-case-1/versions/1"
            ),
            diagnostic_case_version=1,
            terminal_failure_record_ref=record_ref,
            committed_at=NOW,
        )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def commit_bundle(self, **kwargs):
        self.calls.append(kwargs)
        return PostgresReaderRepairMemoryCommitRecord(
            idempotency_key=kwargs["idempotency_key"],
            request_checksum=kwargs["request_checksum"],
            request_id=kwargs["request_id"],
            run_id=kwargs["run_id"],
            terminal_effect_id=kwargs["terminal_effect_id"],
            authorization_ref=kwargs["authorization_ref"],
            identity_scope_ref=kwargs["identity_scope_ref"],
            subject_scope_ref=kwargs["subject_scope_ref"],
            namespace=kwargs["namespace"],
            case_object_id=kwargs["repair_case"].object_id,
            case_version=3,
            strategy_versions=(),
            committed_at=NOW,
        )


def test_failure_diagnostic_handler_commits_quarantined_case_without_public_refs() -> None:
    candidate = _candidate()
    intent = _intent(candidate)
    authorization = _authorization(intent, candidate)
    port = _CommitPort()
    handler = ReaderRepairFailureDiagnosticSideEffectHandler(port)

    outcome = handler.commit(intent, authorization)

    assert len(port.calls) == 1
    assert port.calls[0].candidate.repair_case.successful is False
    assert port.calls[0].candidate.repair_case.payload_after_ref is None
    assert outcome.disposition is HarnessSideEffectDisposition.QUARANTINE
    assert outcome.public_refs == ()
    assert outcome.result_ref == (
        outcome.metadata["failure_diagnostic_receipt"]["checksum"]
    )
    serialized = str(outcome.to_dict()).casefold()
    assert "artifact" not in serialized
    assert "strategy_candidate_bundle" not in serialized
    assert "skill_candidate" not in serialized


def test_postgres_failure_diagnostic_port_writes_one_failed_case_atomically() -> None:
    candidate = _candidate()
    intent = _intent(candidate)
    authorization = _authorization(intent, candidate)
    repository = _Repository()
    handler = ReaderRepairFailureDiagnosticSideEffectHandler(
        PostgresReaderRepairFailureDiagnosticCommitPort(repository)
    )

    outcome = handler.commit(intent, authorization)

    assert len(repository.calls) == 1
    call = repository.calls[0]
    assert call["repair_case"].operation == "harness_failure_diagnostic"
    assert call["repair_case"].successful is False
    assert call["strategies"] == ()
    receipt = outcome.metadata["failure_diagnostic_receipt"]
    assert receipt["diagnostic_case_version"] == 3
    assert receipt["diagnostic_case_ref"].endswith("/versions/3")
    assert outcome.public_refs == ()


def test_failure_diagnostic_candidate_rejects_publication_authority() -> None:
    candidate = _candidate()
    payload = candidate.to_dict()
    payload["repair_case"]["metadata"]["public_ref"] = "artifact://forged"

    with pytest.raises(ValueError, match="forbidden publication"):
        ReaderRepairFailureDiagnosticCandidate.from_dict(payload)


def test_failure_diagnostic_candidate_rejects_mismatched_terminal_shape() -> None:
    candidate = _candidate()
    terminal_failure = replace(
        candidate.terminal_failure,
        terminal_reason_code="graph_terminal_failure",
        record_checksum=None,
    )

    with pytest.raises(ValueError, match="terminal failure identity"):
        replace(
            candidate,
            terminal_failure=terminal_failure,
            checksum=None,
        )


def test_failure_diagnostic_handler_rejects_success_disposition() -> None:
    candidate = _candidate()
    intent = _intent(candidate)
    authorization = replace(
        _authorization(intent, candidate),
        disposition=HarnessSideEffectDisposition.ACCEPTED,
        checksum=None,
    )

    with pytest.raises(HarnessValidationError) as captured:
        ReaderRepairFailureDiagnosticSideEffectHandler(_CommitPort()).commit(
            intent,
            authorization,
        )

    assert captured.value.code == (
        "reader_repair_failure_diagnostic_authority_mismatch"
    )


def test_failure_diagnostic_handler_rejects_unpaired_gate_authority() -> None:
    candidate = _candidate()
    intent = _intent(candidate)
    authorization = replace(
        _authorization(intent, candidate),
        gate_result_refs=(),
        checksum=None,
    )

    with pytest.raises(HarnessValidationError) as captured:
        ReaderRepairFailureDiagnosticSideEffectHandler(_CommitPort()).commit(
            intent,
            authorization,
        )

    assert captured.value.code == (
        "reader_repair_failure_diagnostic_authority_mismatch"
    )


def test_failure_diagnostic_handler_rejects_terminal_decision_substitution() -> None:
    candidate = _candidate()
    intent = _intent(candidate)
    authorization = replace(
        _authorization(intent, candidate),
        causation_id=checksum_for({"decision": "another"}),
        checksum=None,
    )

    with pytest.raises(HarnessValidationError) as captured:
        ReaderRepairFailureDiagnosticSideEffectHandler(_CommitPort()).commit(
            intent,
            authorization,
        )

    assert captured.value.code == (
        "reader_repair_failure_diagnostic_authority_mismatch"
    )


def test_failure_diagnostic_handler_rejects_projection_substitution() -> None:
    candidate = _candidate()
    intent = replace(
        _intent(candidate),
        state_checksum=checksum_for({"state": "another"}),
        checksum=None,
    )
    authorization = _authorization(intent, candidate)

    with pytest.raises(HarnessValidationError) as captured:
        ReaderRepairFailureDiagnosticSideEffectHandler(_CommitPort()).commit(
            intent,
            authorization,
        )

    assert captured.value.code == "reader_repair_failure_diagnostic_intent_invalid"


def _candidate() -> ReaderRepairFailureDiagnosticCandidate:
    failure = _terminal_failure_record()
    assert failure.record_checksum is not None
    assert failure.gate_evidence_refs
    run_id = failure.run_id
    issue = ReaderIssue(
        issue_id="reader-issue-1",
        paper_id="paper-1",
        run_id=run_id,
        issue_type="section_boundary_error",
        severity="high",
        error_signature="section-boundary:paper-1",
        symptom="The source-backed section boundary is missing.",
        source_refs=["paper://paper-1/section-1"],
        payload_ref="reader-payload://paper-1",
    )
    repair_candidate_ref = checksum_for({"candidate": "repair-candidate-1"})
    application_ref = checksum_for({"application": "repair-application-1"})
    observation_ref = checksum_for({"observation": "repair-observation-1"})
    verification_ref = checksum_for({"verification": "failed"})
    input_bindings = {
        "terminal_failure_record": failure.record_checksum,
        "reader_issue": checksum_for(issue.to_dict()),
        "reader_repair_patch_candidate": repair_candidate_ref,
        "reader_repair_application": application_ref,
        "reader_repair_application_observation": observation_ref,
        "reader_repair_application_verification": verification_ref,
    }
    repair_case = ReaderRepairCase(
        repair_case_id="repair-case-1",
        issue=issue,
        memory_kind="episodic",
        repair_strategy="Restore the source-backed section boundary.",
        repair_attempt_refs=["repair-attempt-1"],
        successful=False,
        verification_results=[
            {
                "gate_name": "ReaderRepairApplicationVerificationGate",
                "passed": False,
            }
        ],
        payload_before_ref="reader-payload://paper-1",
        payload_after_ref=None,
        source_refs=issue.source_refs,
        failure_reason="deterministic application verification failed",
        metadata={
            "active_skill_mutation": False,
            "memory_record_kind": "failed_repair_diagnostic",
            "terminal_failure_record_ref": failure.record_checksum,
            "input_bindings": input_bindings,
        },
    )
    candidate_id = stable_research_id(
        "repair_failure_diagnostic",
        run_id,
        failure.record_checksum,
        repair_case.repair_case_id,
    )
    return ReaderRepairFailureDiagnosticCandidate(
        candidate_id=candidate_id,
        run_id=run_id,
        terminal_failure=failure,
        repair_case=repair_case,
        repair_candidate_ref=repair_candidate_ref,
        application_ref=application_ref,
        observation_ref=observation_ref,
        verification_ref=verification_ref,
        failed_gate_evidence_refs=(
            next(
                item
                for item in failure.gate_evidence_refs
                if item in failure.decision_evidence_refs
            ),
        ),
    )


def _intent(
    candidate: ReaderRepairFailureDiagnosticCandidate,
) -> HarnessSideEffectIntent:
    candidate_ref = _candidate_ref(candidate)
    record_ref = candidate.terminal_failure.record_checksum
    assert record_ref is not None
    return HarnessSideEffectIntent(
        effect_id="reader-repair-failure-diagnostic:run-reader-repair-failure",
        kind=READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND,
        run_id=candidate.run_id,
        origin="controller_terminal",
        terminal_action=READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION,
        state_checksum=candidate.terminal_failure.terminal_projection_ref,
        completion_input_ref=record_ref,
        handler=READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
        atomic_group=f"reader-repair-failure-diagnostic:{candidate.run_id}",
        identity_scope_ref=IDENTITY_SCOPE_REF,
        subject_scope_ref=SUBJECT_SCOPE_REF,
        payload={"failure_diagnostic_candidate": candidate.to_dict()},
        candidate_refs=(
            candidate_ref,
            record_ref,
            *candidate.failed_gate_evidence_refs,
        ),
        idempotency_key=f"reader-repair-failure-diagnostic:{candidate.run_id}",
    )


def _authorization(
    intent: HarnessSideEffectIntent,
    candidate: ReaderRepairFailureDiagnosticCandidate,
) -> HarnessSideEffectDecision:
    pairs = set()
    selected = set(candidate.failed_gate_evidence_refs)
    for node in candidate.terminal_failure.failed_nodes:
        for evidence in node.gate_evidence:
            if evidence.evidence_ref in selected:
                assert evidence.contract_ref is not None
                pairs.add((evidence.contract_ref.exact_ref, evidence.evidence_ref))
    ordered_pairs = tuple(sorted(pairs))
    return HarnessSideEffectDecision(
        decision_id="reader-repair-failure-diagnostic-authorization",
        intent_ref=intent.checksum,
        effect_id=intent.effect_id,
        kind=intent.kind,
        origin=intent.origin,
        run_id=intent.run_id,
        handler=READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF,
        identity_scope_ref=intent.identity_scope_ref,
        subject_scope_ref=intent.subject_scope_ref,
        atomic_group=intent.atomic_group,
        idempotency_key=intent.idempotency_key,
        command_ordinal=1,
        causation_id=candidate.terminal_failure.terminal_decision_ref,
        disposition=HarnessSideEffectDisposition.QUARANTINE,
        terminal_action=intent.terminal_action,
        terminal_state_ref=intent.state_checksum,
        gate_refs=tuple(item[0] for item in ordered_pairs),
        gate_result_refs=tuple(item[1] for item in ordered_pairs),
        aggregate_verdict_ref=checksum_for({"verdict": "failed"}),
        approval_evidence_ref=checksum_for({"approval": "not_required"}),
        budget_ref=checksum_for({"budget": "inherited"}),
    )


def _terminal_failure_record() -> HarnessGraphTerminalFailureRecord:
    run_id = "run-reader-repair-failure"
    port = InMemoryHarnessEventPort()
    workflow = HarnessWorkflowSpec(
        workflow_id="research.reader_repair.graph",
        steps=(
            HarnessStepSpec(
                step_id="verify_repair_application",
                worker_type="function",
                metadata={
                    "output_schema": {
                        "required": ["reader_repair_application_verification"]
                    }
                },
            ),
        ),
        entry_step_id="verify_repair_application",
    )
    HarnessControlPlane(
        event_port=port,
        worker_registry={
            "verify_repair_application": lambda _task: HarnessWorkerResult(
                status="succeeded",
                output={"unexpected": "candidate"},
            ),
        },
    ).run(HarnessRunSpec(run_id=run_id, workflow=workflow))
    recovery = port.recover_graph(run_id)
    decision = next(
        item
        for item in recovery.decision_commits
        if item.decision.decision_type is HarnessGraphDecisionType.HALT_RUN
        and item.decision.reason_code == "verification_failed_replans_exhausted"
    )
    projection = next(
        item
        for item in recovery.projection_commits
        if item.cause_checksum == decision.decision.decision_checksum
    )
    return HarnessGraphTerminalFailureRecord.from_commits(decision, projection)


def _candidate_ref(candidate: ReaderRepairFailureDiagnosticCandidate) -> str:
    if candidate.checksum is None:  # pragma: no cover - model invariant
        raise AssertionError("candidate checksum is missing")
    return candidate.checksum
