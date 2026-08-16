from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from framework.events.canonical import checksum_for
from framework.harness import HarnessWorkerStatus

from business.research.domain import (
    ReaderIssue,
    ReaderNavigationItem,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ResearchDocument,
    ResearchSection,
    SourceLineage,
    stable_research_id,
)
from business.research.graphs import (
    READER_REPAIR_EXECUTION_GATE_REFERENCES,
    build_reader_repair_application_verification_worker_result,
    build_reader_repair_application_worker_result,
    build_reader_repair_execution_gate_registry,
)
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import (
    apply_reader_repair_candidate,
    reader_repair_component_checksum,
    verify_reader_repair_application,
)
from tests.business.research.fakes import FakeResearchSourceProvider


SOURCE_REF = "paper://paper-harness-001/raw"


def test_reader_repair_execution_gate_chain_recomputes_exact_candidates() -> None:
    payload = _payload()
    issue = _issue(payload)
    context_pack = _context_pack(issue)
    candidate = _candidate(payload, context_pack)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    observation = _observation(candidate, application)
    verification = verify_reader_repair_application(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
    )
    registry = build_reader_repair_execution_gate_registry()

    cases = (
        (
            "ReaderRepairPatchCandidateGate@1",
            {"reader_repair_patch_candidate": candidate.to_dict()},
            {
                "reader_issue": issue.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
        ),
        (
            "ReaderRepairApplicationCandidateGate@1",
            {"reader_repair_application_candidate": application.to_dict()},
            {"reader_repair_patch_candidate": candidate.to_dict()},
        ),
        (
            "ReaderRepairApplicationObservationGate@1",
            {"reader_repair_application_observation": observation.to_dict()},
            {
                "reader_issue": issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
            },
        ),
        (
            "ReaderRepairApplicationVerificationGate@1",
            {
                "reader_repair_application_verification": verification.to_dict()
            },
            {
                "reader_issue": issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
                "reader_repair_application_observation": observation.to_dict(),
            },
        ),
    )
    results = [
        registry.resolve(reference).gate.evaluate(
            _gate_context(output, prior=prior, payload=payload)
        )
        for reference, output, prior in cases
    ]

    assert tuple(READER_REPAIR_EXECUTION_GATE_REFERENCES) == tuple(
        reference for reference, _, _ in cases
    )
    assert all(result.passed for result in results)
    assert all(
        result.details["reason_code"]
        == "reader_repair_execution_contract_passed"
        for result in results
    )


def test_reader_repair_execution_function_workers_return_candidates_only() -> None:
    payload = _payload()
    issue = _issue(payload)
    candidate = _candidate(payload, _context_pack(issue))

    application_result = build_reader_repair_application_worker_result(
        payload=payload,
        candidate=candidate,
    )
    application = ReaderRepairApplicationCandidate.model_validate(
        application_result.output["reader_repair_application_candidate"]
    )
    observation = _observation(candidate, application)
    verification_result = (
        build_reader_repair_application_verification_worker_result(
            payload=payload,
            issue=issue,
            candidate=candidate,
            application=application,
            observation=observation,
        )
    )

    assert application_result.status is HarnessWorkerStatus.SUCCEEDED
    assert verification_result.status is HarnessWorkerStatus.SUCCEEDED
    assert application_result.effect_intent is None
    assert verification_result.effect_intent is None
    assert set(application_result.output) == {
        "reader_repair_application_candidate"
    }
    assert set(verification_result.output) == {
        "reader_repair_application_verification"
    }


def test_reader_repair_execution_workers_have_no_side_effect_owner_imports() -> None:
    source = Path(
        "business/research/graphs/reader_repair_execution_workers.py"
    ).read_text(encoding="utf-8").casefold()

    assert "artifact" not in source
    assert "memory" not in source
    assert "storage" not in source
    assert "store" not in source


def test_patch_candidate_gate_rejects_stale_component_checksum() -> None:
    payload = _payload()
    issue = _issue(payload)
    context_pack = _context_pack(issue)
    raw_candidate = _candidate(payload, context_pack).to_dict()
    raw_candidate["patch_operations"][0]["expected_before_checksum"] = checksum_for(
        {"stale": True}
    )
    candidate = ReaderRepairPatchCandidate.model_validate(raw_candidate)
    gate = build_reader_repair_execution_gate_registry().resolve(
        "ReaderRepairPatchCandidateGate@1"
    ).gate

    result = gate.evaluate(
        _gate_context(
            {"reader_repair_patch_candidate": candidate.to_dict()},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_context_pack": context_pack.to_dict(),
            },
            payload=payload,
        )
    )

    assert result.passed is False
    assert result.details["violations"]["application"]["code"] == (
        "reader_repair_patch_before_checksum_mismatch"
    )


def test_application_gate_rejects_worker_payload_substitution() -> None:
    payload = _payload()
    context_pack = _context_pack(_issue(payload))
    candidate = _candidate(payload, context_pack)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    tampered = application.to_dict()
    tampered["after_payload"]["navigation"] = []
    tampered["after_payload_checksum"] = checksum_for(tampered["after_payload"])
    substituted = ReaderRepairApplicationCandidate.model_validate(tampered)
    gate = build_reader_repair_execution_gate_registry().resolve(
        "ReaderRepairApplicationCandidateGate@1"
    ).gate

    result = gate.evaluate(
        _gate_context(
            {"reader_repair_application_candidate": substituted.to_dict()},
            prior={"reader_repair_patch_candidate": candidate.to_dict()},
            payload=payload,
        )
    )

    assert result.passed is False
    assert "application_candidate" in result.details["violations"]


def test_observation_gate_rejects_evidence_outside_issue_scope() -> None:
    payload = _payload()
    issue = _issue(payload)
    candidate = _candidate(payload, _context_pack(issue))
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    observation = _observation(
        candidate,
        application,
        source_ref="paper://other/raw",
    )
    gate = build_reader_repair_execution_gate_registry().resolve(
        "ReaderRepairApplicationObservationGate@1"
    ).gate

    result = gate.evaluate(
        _gate_context(
            {"reader_repair_application_observation": observation.to_dict()},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
            },
            payload=payload,
        )
    )

    assert result.passed is False
    assert result.details["violations"]["outside_source_refs"] == [
        "paper://other/raw"
    ]


def test_verification_gate_ignores_worker_claim_and_fails_invalid_navigation() -> None:
    payload = _payload()
    issue = _issue(payload)
    candidate = _candidate(payload, _context_pack(issue))
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    tampered = application.to_dict()
    tampered["after_payload"]["navigation"] = []
    tampered["after_payload_checksum"] = checksum_for(tampered["after_payload"])
    invalid_application = ReaderRepairApplicationCandidate.model_validate(tampered)
    observation = _observation(
        candidate,
        invalid_application,
        finding="The candidate passes every check.",
    )
    record = verify_reader_repair_application(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=invalid_application,
        observation=observation,
    )
    gate = build_reader_repair_execution_gate_registry().resolve(
        "ReaderRepairApplicationVerificationGate@1"
    ).gate

    result = gate.evaluate(
        _gate_context(
            {"reader_repair_application_verification": record.to_dict()},
            prior={
                "reader_issue": issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": (
                    invalid_application.to_dict()
                ),
                "reader_repair_application_observation": observation.to_dict(),
            },
            payload=payload,
        )
    )

    assert result.passed is False
    assert "application_binding" in result.details["violations"]["failed_checks"]
    assert "reader_navigation" in result.details["violations"]["failed_checks"]


def test_execution_gate_fails_closed_without_root_payload() -> None:
    payload = _payload()
    issue = _issue(payload)
    context_pack = _context_pack(issue)
    candidate = _candidate(payload, context_pack)
    gate = build_reader_repair_execution_gate_registry().resolve(
        "ReaderRepairPatchCandidateGate@1"
    ).gate
    context = _gate_context(
        {"reader_repair_patch_candidate": candidate.to_dict()},
        prior={
            "reader_issue": issue.to_dict(),
            "reader_repair_context_pack": context_pack.to_dict(),
        },
        payload=None,
    )

    result = gate.evaluate(context)

    assert result.passed is False
    assert result.details["reason_code"] == (
        "reader_repair_execution_gate_input_invalid"
    )


def _gate_context(output, *, prior, payload):
    outputs = {key: {key: value} for key, value in prior.items()}
    inputs = {} if payload is None else {"reader_payload": payload.to_dict()}
    return SimpleNamespace(
        worker_result=SimpleNamespace(output=output),
        state=SimpleNamespace(
            metadata={"outputs": outputs},
            run_spec=SimpleNamespace(inputs=inputs),
        ),
    )


def _payload():
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair-execution-gate",
        sections=[],
        lineage=SourceLineage(source_refs=[SOURCE_REF]),
    )
    return ReaderPayloadBuilder().build(paper=paper, document=document)


def _issue(payload) -> ReaderIssue:
    return ReaderIssue(
        issue_id="reader-repair-execution-issue",
        paper_id=payload.paper.paper_id,
        run_id="reader-repair-execution-run",
        step_id="build_reader_payload",
        issue_type="section_boundary_error",
        severity="high",
        error_signature="section-boundary:missing",
        symptom="Reader document and navigation have no sections.",
        source_refs=[SOURCE_REF],
        payload_ref=payload.payload_id,
    )


def _context_pack(issue: ReaderIssue) -> ReaderRepairContextPack:
    return ReaderRepairContextPack(
        context_id="reader-repair-execution-context",
        issue=issue,
        source_lineage=SourceLineage(source_refs=issue.source_refs),
        source_refs=issue.source_refs,
        failure_case_gap_report={"no_failed_cases_available": True},
    )


def _candidate(
    payload,
    context_pack: ReaderRepairContextPack,
) -> ReaderRepairPatchCandidate:
    section = ResearchSection(
        section_id="section-1",
        title="Introduction",
        text="Source-backed introduction.",
        source_ref=SOURCE_REF,
    )
    document = ResearchDocument(
        paper_id=payload.paper.paper_id,
        source_hash=payload.document.source_hash,
        sections=[section],
        lineage=payload.document.lineage,
    )
    navigation = ReaderNavigationItem(
        item_id=stable_research_id(
            "nav",
            payload.paper.paper_id,
            section.section_id,
        ),
        title=section.title,
        target_ref=section.section_id,
        order=0,
    )
    return ReaderRepairPatchCandidate(
        candidate_id="reader-repair-execution-candidate",
        repair_summary="Restore the source-backed section and navigation.",
        target_region_refs=[SOURCE_REF],
        patch_operations=[
            {
                "op": "replace_document",
                "operation_id": "replace-document",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "document",
                ),
                "source_refs": [SOURCE_REF],
                "replacement": document,
            },
            {
                "op": "replace_navigation",
                "operation_id": "replace-navigation",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "navigation",
                ),
                "source_refs": [SOURCE_REF],
                "replacement": [navigation],
            },
        ],
        expected_effect="Reader navigation matches the repaired document.",
        confidence=0.9,
        metadata={
            "input_bindings": {
                "reader_payload": checksum_for(payload.to_dict()),
                "reader_repair_context_pack": checksum_for(
                    context_pack.to_dict()
                ),
            }
        },
    )


def _observation(
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
    *,
    source_ref: str = SOURCE_REF,
    finding: str = "The application is source-backed.",
) -> ReaderRepairApplicationObservationCandidate:
    return ReaderRepairApplicationObservationCandidate(
        candidate_id=candidate.candidate_id,
        application_id=application.application_id,
        observations=[
            {
                "check_id": "source-backed-application",
                "finding": finding,
                "evidence_refs": [source_ref],
            }
        ],
        source_refs=[source_ref],
        input_bindings={
            "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
            "reader_repair_application_candidate": checksum_for(
                application.to_dict()
            ),
        },
    )
