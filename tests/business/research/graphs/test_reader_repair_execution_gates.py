from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessCommittedNodeOutputReceipt,
    HarnessGraphReference,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputResourceIdentity,
    HarnessValidationError,
    HarnessWorkerStatus,
)
from framework.harness.graph import HarnessContractKind, HarnessContractReference
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)

from business.research.domain import (
    ReaderIssue,
    ReaderNavigationItem,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairContextPack,
    ReaderRepairPatchCandidate,
    ReaderRepairResult,
    ResearchDocument,
    ResearchSection,
    SourceLineage,
    stable_research_id,
)
from business.research.graphs import (
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    READER_REPAIR_EXECUTION_GATE_REFERENCES,
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    READER_REPAIR_RESULT_OUTPUT_KEY,
    build_reader_repair_application_verification_worker_result,
    build_reader_repair_application_worker_result,
    build_reader_repair_execution_gate_registry,
    build_reader_repair_graph_definition,
    build_reader_repair_result_worker_result,
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
    definition = build_reader_repair_graph_definition()
    assert definition.definition_checksum is not None
    receipt = _receipt(
        application,
        graph_definition_checksum=definition.definition_checksum,
    )
    result_output = build_reader_repair_result_worker_result(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
        verification=verification,
        receipt=receipt,
        graph_definition_checksum=definition.definition_checksum,
    ).output
    registry = build_reader_repair_execution_gate_registry(
        graph_definition_checksum=definition.definition_checksum,
    )

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
        (
            "ReaderRepairCommittedResultGate@1",
            result_output,
            {
                "reader_issue": issue.to_dict(),
                "reader_repair_patch_candidate": candidate.to_dict(),
                "reader_repair_application_candidate": application.to_dict(),
                "reader_repair_application_observation": observation.to_dict(),
                "reader_repair_application_verification": verification.to_dict(),
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


def test_reader_repair_result_worker_binds_real_payload_and_commit_receipt() -> None:
    payload = _payload()
    issue = _issue(payload)
    candidate = _candidate(payload, _context_pack(issue))
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
    definition = build_reader_repair_graph_definition()
    assert definition.definition_checksum is not None
    receipt = _receipt(
        application,
        graph_definition_checksum=definition.definition_checksum,
    )

    worker_result = build_reader_repair_result_worker_result(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
        verification=verification,
        receipt=receipt,
        graph_definition_checksum=definition.definition_checksum,
    )
    result = ReaderRepairResult.model_validate(
        worker_result.output[READER_REPAIR_RESULT_OUTPUT_KEY]
    )

    assert worker_result.status is HarnessWorkerStatus.SUCCEEDED
    assert worker_result.effect_intent is None
    assert set(worker_result.output) == {
        READER_REPAIR_RESULT_OUTPUT_KEY,
        READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    }
    assert result.successful is True
    assert result.payload_before_ref == payload.payload_id
    assert result.payload_after_ref == application.after_payload_checksum
    assert result.application_id == application.application_id
    assert result.committed_output is not None
    assert result.committed_output.receipt_ref == receipt.receipt_ref
    assert result.committed_output.commit_ref == receipt.commit.commit_ref
    assert result.committed_output.output_ref == checksum_for(application.to_dict())
    assert result.committed_output.payload_checksum == (
        application.after_payload_checksum
    )
    assert "public_ref" not in result.to_dict()
    assert "artifact_ref" not in result.to_dict()

    partial = result.to_dict()
    partial.pop("committed_output")
    with pytest.raises(ValueError, match="requires application, verification"):
        ReaderRepairResult.model_validate(partial)

    blank_application = result.to_dict()
    blank_application["application_id"] = ""
    with pytest.raises(ValueError, match="application id"):
        ReaderRepairResult.model_validate(blank_application)


def test_committed_result_gate_rejects_tampered_business_proof() -> None:
    fixture = _committed_result_fixture()
    output = dict(fixture["output"])
    raw_result = dict(output[READER_REPAIR_RESULT_OUTPUT_KEY])
    raw_proof = dict(raw_result["committed_output"])
    raw_proof["commit_ref"] = checksum_for({"forged": True})
    raw_result["committed_output"] = raw_proof
    output[READER_REPAIR_RESULT_OUTPUT_KEY] = raw_result

    gate_result = fixture["gate"].evaluate(
        _gate_context(
            output,
            prior=fixture["prior"],
            payload=fixture["payload"],
        )
    )

    assert gate_result.passed is False
    assert "reader_repair_result" in gate_result.details["violations"]


def test_committed_result_gate_rejects_receipt_checksum_tampering() -> None:
    fixture = _committed_result_fixture()
    output = dict(fixture["output"])
    raw_receipt = dict(output[READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY])
    raw_receipt["receipt_ref"] = checksum_for({"forged": True})
    output[READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY] = raw_receipt

    gate_result = fixture["gate"].evaluate(
        _gate_context(
            output,
            prior=fixture["prior"],
            payload=fixture["payload"],
        )
    )

    assert gate_result.passed is False
    assert gate_result.details["reason_code"] == (
        "reader_repair_execution_gate_input_invalid"
    )
    assert gate_result.details["error_code"] == (
        "graph_committed_node_output_receipt_checksum_invalid"
    )


def test_committed_result_worker_rejects_wrong_graph_definition() -> None:
    fixture = _committed_result_fixture()
    build_args = dict(fixture["build_args"])
    build_args["graph_definition_checksum"] = checksum_for(
        {"definition": "wrong"}
    )

    with pytest.raises(HarnessValidationError) as captured:
        build_reader_repair_result_worker_result(**build_args)

    assert captured.value.code == "reader_repair_committed_result_invalid"
    assert captured.value.details["violations"]["committed_output_receipt"] == {
        "mismatches": ["graph_definition_checksum"]
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


def _committed_result_fixture():
    payload = _payload()
    issue = _issue(payload)
    candidate = _candidate(payload, _context_pack(issue))
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
    definition = build_reader_repair_graph_definition()
    assert definition.definition_checksum is not None
    receipt = _receipt(
        application,
        graph_definition_checksum=definition.definition_checksum,
    )
    build_args = {
        "payload": payload,
        "issue": issue,
        "candidate": candidate,
        "application": application,
        "observation": observation,
        "verification": verification,
        "receipt": receipt,
        "graph_definition_checksum": definition.definition_checksum,
    }
    output = build_reader_repair_result_worker_result(
        **build_args,
    ).output
    gate = build_reader_repair_execution_gate_registry(
        graph_definition_checksum=definition.definition_checksum,
    ).resolve("ReaderRepairCommittedResultGate@1").gate
    return {
        "payload": payload,
        "output": output,
        "gate": gate,
        "build_args": build_args,
        "prior": {
            "reader_issue": issue.to_dict(),
            "reader_repair_patch_candidate": candidate.to_dict(),
            "reader_repair_application_candidate": application.to_dict(),
            "reader_repair_application_observation": observation.to_dict(),
            "reader_repair_application_verification": verification.to_dict(),
        },
    }


def _receipt(
    application: ReaderRepairApplicationCandidate,
    *,
    graph_definition_checksum: str,
) -> HarnessCommittedNodeOutputReceipt:
    graph_ref = HarnessGraphReference(
        graph_id=READER_REPAIR_GRAPH_ID,
        graph_ref=HarnessContractReference(
            HarnessContractKind.GRAPH,
            READER_REPAIR_GRAPH_ID,
            READER_REPAIR_GRAPH_VERSION,
        ),
        schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=checksum_for({"graph": READER_REPAIR_GRAPH_ID, "version": "2"}),
    )
    resource = HarnessNodeOutputResourceIdentity(
        run_id="reader-repair-execution-run",
        graph_ref=graph_ref,
        node_id=READER_REPAIR_APPLICATION_STEP_ID,
        node_instance_id="reader-repair-application-node-instance-1",
    )
    candidate = HarnessNodeOutputCandidate(
        output_refs={
            READER_REPAIR_APPLICATION_OUTPUT_KEY: checksum_for(
                application.to_dict()
            )
        },
        evidence_refs=(checksum_for({"source_ref": SOURCE_REF}),),
    )
    commit = HarnessNodeOutputCommit(
        stage_ref=checksum_for({"stage": "reader-repair-application"}),
        lease_ref=checksum_for({"lease": "reader-repair-application"}),
        resource_ref=resource.resource_ref,
        activity_id="reader-repair-application-activity-instance",
        owner_attempt_id="reader-repair-application-attempt-1",
        generation=1,
        candidate=candidate,
        committed_at=datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
    )
    return HarnessCommittedNodeOutputReceipt(
        graph_definition_checksum=graph_definition_checksum,
        binding_id=READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
        receipt_input_key=READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
        producer_activity_id=READER_REPAIR_APPLICATION_STEP_ID,
        producer_activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            "research.reader_repair.apply_repair_candidate",
            "1",
        ),
        resource=resource,
        commit=commit,
        output_key=READER_REPAIR_APPLICATION_OUTPUT_KEY,
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
