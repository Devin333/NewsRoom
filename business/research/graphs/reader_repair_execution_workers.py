from __future__ import annotations

from framework.harness import HarnessWorkerResult, HarnessWorkerStatus

from business.research.domain import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairPatchCandidate,
    ResearchReaderPayload,
)
from business.research.reader_repair.application import (
    apply_reader_repair_candidate,
    verify_reader_repair_application,
)


READER_REPAIR_APPLICATION_STEP_ID = "apply_repair_candidate"
READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID = "verify_repair_application"


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
            "reader_repair_application_candidate": application.to_dict(),
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
            "reader_repair_application_verification": verification.to_dict(),
        },
    )


__all__ = [
    "READER_REPAIR_APPLICATION_STEP_ID",
    "READER_REPAIR_APPLICATION_VERIFICATION_STEP_ID",
    "build_reader_repair_application_verification_worker_result",
    "build_reader_repair_application_worker_result",
]
