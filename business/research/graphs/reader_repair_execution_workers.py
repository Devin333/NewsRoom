from __future__ import annotations

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessCommittedNodeOutputReceipt,
    HarnessValidationError,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)

from business.research.domain import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairApplicationVerificationRecord,
    ReaderRepairCommittedOutputProof,
    ReaderRepairPatchCandidate,
    ReaderRepairResult,
    ResearchReaderPayload,
    stable_research_id,
)
from business.research.graphs.reader_repair_contracts import (
    READER_REPAIR_APPLICATION_ACTIVITY_REF,
    READER_REPAIR_APPLICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_STEP_ID,
    READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY,
    READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID,
    READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
    READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
    READER_REPAIR_GRAPH_ID,
    READER_REPAIR_GRAPH_VERSION,
    READER_REPAIR_RESULT_OUTPUT_KEY,
    READER_REPAIR_RESULT_STEP_ID,
)
from business.research.reader_repair.application import (
    apply_reader_repair_candidate,
    verify_reader_repair_application,
)


def build_reader_repair_application_worker_result(
    *,
    payload: ResearchReaderPayload,
    candidate: ReaderRepairPatchCandidate,
) -> HarnessWorkerResult:
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output={
            READER_REPAIR_APPLICATION_OUTPUT_KEY: application.to_dict(),
        },
    )


def build_reader_repair_application_verification_worker_result(
    *,
    payload: ResearchReaderPayload,
    issue: ReaderIssue,
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
    observation: ReaderRepairApplicationObservationCandidate,
) -> HarnessWorkerResult:
    verification = verify_reader_repair_application(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
    )
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output={
            READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY: (
                verification.to_dict()
            ),
        },
    )


def build_reader_repair_committed_result(
    *,
    payload: ResearchReaderPayload,
    issue: ReaderIssue,
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
    observation: ReaderRepairApplicationObservationCandidate,
    verification: ReaderRepairApplicationVerificationRecord,
    receipt: HarnessCommittedNodeOutputReceipt,
    graph_definition_checksum: str,
) -> ReaderRepairResult:
    expected_verification = verify_reader_repair_application(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
    )
    violations: dict[str, object] = {}
    if verification != expected_verification:
        violations["verification"] = (
            "must equal the deterministic application verification"
        )
    if not expected_verification.successful:
        violations["verification_successful"] = False
    expected_receipt_identity = {
        "graph_definition_checksum": graph_definition_checksum,
        "binding_id": READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID,
        "receipt_input_key": READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY,
        "producer_activity_id": READER_REPAIR_APPLICATION_STEP_ID,
        "producer_activity_ref": READER_REPAIR_APPLICATION_ACTIVITY_REF,
        "producer_node_id": READER_REPAIR_APPLICATION_STEP_ID,
        "producer_output_key": READER_REPAIR_APPLICATION_OUTPUT_KEY,
        "graph_id": READER_REPAIR_GRAPH_ID,
        "graph_version": READER_REPAIR_GRAPH_VERSION,
    }
    actual_receipt_identity = {
        "graph_definition_checksum": receipt.graph_definition_checksum,
        "binding_id": receipt.binding_id,
        "receipt_input_key": receipt.receipt_input_key,
        "producer_activity_id": receipt.producer_activity_id,
        "producer_activity_ref": receipt.producer_activity_ref.exact_ref,
        "producer_node_id": receipt.resource.node_id,
        "producer_output_key": receipt.output_key,
        "graph_id": receipt.resource.graph_ref.graph_id,
        "graph_version": receipt.resource.graph_ref.workflow_ref.version,
    }
    receipt_mismatches = sorted(
        key
        for key, expected in expected_receipt_identity.items()
        if actual_receipt_identity[key] != expected
    )
    if issue.run_id is not None and receipt.resource.run_id != issue.run_id:
        receipt_mismatches.append("run_id")
    if receipt_mismatches:
        violations["committed_output_receipt"] = {
            "mismatches": receipt_mismatches,
        }
    try:
        receipt.assert_matches_payload(application.to_dict())
    except HarnessValidationError as exc:
        violations["committed_output_payload"] = exc.code
    if violations:
        raise HarnessValidationError(
            "reader repair result requires a verified committed application",
            code="reader_repair_committed_result_invalid",
            details={"violations": violations},
        )

    attempt_id = stable_research_id(
        "repair_attempt",
        issue.issue_id,
        candidate.candidate_id,
    )
    verification_ref = checksum_for(verification.to_dict())
    proof = ReaderRepairCommittedOutputProof(
        binding_id=receipt.binding_id,
        receipt_ref=receipt.receipt_ref,
        graph_definition_checksum=receipt.graph_definition_checksum,
        resource_ref=receipt.resource.resource_ref,
        commit_ref=receipt.commit.commit_ref,
        producer_activity_id=receipt.producer_activity_id,
        producer_node_id=receipt.resource.node_id,
        producer_node_instance_id=receipt.resource.node_instance_id,
        output_key=receipt.output_key,
        output_ref=receipt.output_ref,
        payload_checksum=application.after_payload_checksum,
    )
    input_bindings = {
        "reader_payload": checksum_for(payload.to_dict()),
        "reader_issue": checksum_for(issue.to_dict()),
        "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
        READER_REPAIR_APPLICATION_OUTPUT_KEY: checksum_for(application.to_dict()),
        "reader_repair_application_observation": checksum_for(
            observation.to_dict()
        ),
        READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY: verification_ref,
        READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY: checksum_for(
            receipt.to_dict()
        ),
    }
    return ReaderRepairResult(
        result_id=stable_research_id(
            "repair_result",
            attempt_id,
            application.application_id,
            verification.verification_id,
            receipt.receipt_ref,
        ),
        attempt_id=attempt_id,
        successful=True,
        verification_results=[
            {
                "gate_name": "ReaderRepairApplicationVerificationGate@1",
                **check.to_dict(),
            }
            for check in verification.checks
        ],
        payload_before_ref=payload.payload_id,
        payload_after_ref=application.after_payload_checksum,
        source_refs=issue.source_refs,
        application_id=application.application_id,
        application_verification_ref=verification_ref,
        committed_output=proof,
        metadata={
            "candidate_id": candidate.candidate_id,
            "repair_summary": candidate.repair_summary,
            "skill_promotion_triggered": False,
            "input_bindings": input_bindings,
        },
    )


def build_reader_repair_result_worker_result(
    *,
    payload: ResearchReaderPayload,
    issue: ReaderIssue,
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
    observation: ReaderRepairApplicationObservationCandidate,
    verification: ReaderRepairApplicationVerificationRecord,
    receipt: HarnessCommittedNodeOutputReceipt,
    graph_definition_checksum: str,
) -> HarnessWorkerResult:
    result = build_reader_repair_committed_result(
        payload=payload,
        issue=issue,
        candidate=candidate,
        application=application,
        observation=observation,
        verification=verification,
        receipt=receipt,
        graph_definition_checksum=graph_definition_checksum,
    )
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output={
            READER_REPAIR_RESULT_OUTPUT_KEY: result.to_dict(),
            READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY: receipt.to_dict(),
        },
    )


__all__ = [
    "READER_REPAIR_APPLICATION_ACTIVITY_REF",
    "READER_REPAIR_APPLICATION_OUTPUT_KEY",
    "READER_REPAIR_APPLICATION_STEP_ID",
    "READER_REPAIR_APPLICATION_VERIFICATION_OUTPUT_KEY",
    "READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID",
    "READER_REPAIR_COMMITTED_OUTPUT_BINDING_ID",
    "READER_REPAIR_COMMITTED_OUTPUT_RECEIPT_KEY",
    "READER_REPAIR_RESULT_OUTPUT_KEY",
    "READER_REPAIR_RESULT_STEP_ID",
    "build_reader_repair_application_verification_worker_result",
    "build_reader_repair_application_worker_result",
    "build_reader_repair_committed_result",
    "build_reader_repair_result_worker_result",
]
