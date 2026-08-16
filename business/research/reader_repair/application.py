from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.events.canonical import checksum_for

from business.research.domain import ResearchReaderPayload, stable_research_id
from business.research.domain.reader_repair import (
    ReaderIssue,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationCheck,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairApplicationVerificationRecord,
    ReaderRepairPatchCandidate,
    ReaderRepairPatchOperationBase,
    ReaderRepairRemoveAnalysisOperation,
    ReaderRepairRemoveEvidenceOperation,
    ReaderRepairReplaceAnalysisOperation,
    ReaderRepairReplaceAnnotationsOperation,
    ReaderRepairReplaceDocumentOperation,
    ReaderRepairReplaceEvidenceOperation,
    ReaderRepairReplaceNavigationOperation,
    ReaderRepairReplaceQualityOperation,
    ReaderRepairReplaceSourceLineageOperation,
    reader_repair_patch_operation_target,
)
from business.research.reader.gates import (
    validate_reader_navigation,
    validate_reader_payload_schema,
    validate_reader_source_lineage,
)


_PATCH_TARGETS = frozenset(
    {
        "document",
        "analysis",
        "evidence",
        "navigation",
        "annotations",
        "source_lineage",
        "quality",
    }
)


class ReaderRepairApplicationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


def reader_repair_component_checksum(
    payload: ResearchReaderPayload,
    target: str,
) -> str:
    if not isinstance(payload, ResearchReaderPayload):
        raise TypeError("payload must be ResearchReaderPayload")
    normalized_target = str(target).strip()
    if normalized_target not in _PATCH_TARGETS:
        raise ReaderRepairApplicationError(
            "reader repair patch target is unsupported",
            code="reader_repair_patch_target_unsupported",
            details={"target": normalized_target},
        )
    return checksum_for(_component_projection(payload, normalized_target))


def apply_reader_repair_candidate(
    *,
    payload: ResearchReaderPayload,
    candidate: ReaderRepairPatchCandidate,
) -> ReaderRepairApplicationCandidate:
    if not isinstance(payload, ResearchReaderPayload):
        raise TypeError("payload must be ResearchReaderPayload")
    if not isinstance(candidate, ReaderRepairPatchCandidate):
        raise TypeError("candidate must be ReaderRepairPatchCandidate")

    payload_before_checksum = checksum_for(payload.to_dict())
    payload_data = payload.to_dict()
    changed_targets: list[str] = []
    for operation in candidate.patch_operations:
        target = reader_repair_patch_operation_target(operation)
        actual_before_checksum = reader_repair_component_checksum(payload, target)
        if operation.expected_before_checksum != actual_before_checksum:
            raise ReaderRepairApplicationError(
                "reader repair patch expected checksum does not match input",
                code="reader_repair_patch_before_checksum_mismatch",
                details={
                    "operation_id": operation.operation_id,
                    "target": target,
                    "expected": operation.expected_before_checksum,
                    "actual": actual_before_checksum,
                },
            )
        replacement = _operation_replacement(operation)
        if checksum_for(replacement) != actual_before_checksum:
            changed_targets.append(target)
        if replacement is None:
            payload_data.pop(target, None)
        else:
            payload_data[target] = replacement

    if not changed_targets:
        raise ReaderRepairApplicationError(
            "reader repair patch must change at least one declared target",
            code="reader_repair_patch_no_effect",
        )

    # A candidate cannot declare itself ready. Only deterministic VERIFY can do so.
    payload_data["status"] = "pending"
    try:
        after_payload = ResearchReaderPayload.model_validate(payload_data)
    except (TypeError, ValueError) as exc:
        raise ReaderRepairApplicationError(
            "reader repair patch does not produce a valid reader payload",
            code="reader_repair_patch_payload_invalid",
            details={"error_type": type(exc).__name__},
        ) from exc
    if after_payload.payload_id != payload.payload_id or after_payload.paper != payload.paper:
        raise ReaderRepairApplicationError(
            "reader repair patch changed immutable payload identity",
            code="reader_repair_patch_identity_changed",
        )
    before_projection = payload.to_dict()
    after_projection = after_payload.to_dict()
    allowed_source_refs = {
        *_collect_named_refs(before_projection, keys={"source_ref", "source_refs"}),
        *candidate.target_region_refs,
    }
    introduced_source_refs = sorted(
        _collect_named_refs(
            after_projection,
            keys={"source_ref", "source_refs"},
        )
        - allowed_source_refs
    )
    if introduced_source_refs:
        raise ReaderRepairApplicationError(
            "reader repair patch introduced undeclared source refs",
            code="reader_repair_patch_source_scope_expanded",
            details={"source_refs": introduced_source_refs},
        )
    before_artifact_refs = _collect_named_refs(
        before_projection,
        keys={"artifact_refs"},
    )
    after_artifact_refs = _collect_named_refs(
        after_projection,
        keys={"artifact_refs"},
    )
    if after_artifact_refs != before_artifact_refs:
        raise ReaderRepairApplicationError(
            "reader repair patch changed Artifact lineage authority",
            code="reader_repair_patch_artifact_lineage_changed",
        )
    if after_payload.document.source_hash != payload.document.source_hash:
        raise ReaderRepairApplicationError(
            "reader repair patch changed immutable source identity",
            code="reader_repair_patch_source_identity_changed",
        )

    candidate_checksum = checksum_for(candidate.to_dict())
    after_payload_checksum = checksum_for(after_payload.to_dict())
    application_id = stable_research_id(
        "reader_repair_application",
        candidate.candidate_id,
        payload_before_checksum,
        after_payload_checksum,
    )
    return ReaderRepairApplicationCandidate(
        application_id=application_id,
        candidate_id=candidate.candidate_id,
        before_payload_checksum=payload_before_checksum,
        after_payload=after_payload,
        after_payload_checksum=after_payload_checksum,
        applied_operation_ids=[
            operation.operation_id for operation in candidate.patch_operations
        ],
        target_region_refs=candidate.target_region_refs,
        source_refs=candidate.target_region_refs,
        input_bindings={
            "reader_payload": payload_before_checksum,
            "reader_repair_patch_candidate": candidate_checksum,
        },
    )


def verify_reader_repair_application(
    *,
    payload: ResearchReaderPayload,
    issue: ReaderIssue,
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
    observation: ReaderRepairApplicationObservationCandidate,
) -> ReaderRepairApplicationVerificationRecord:
    if not isinstance(payload, ResearchReaderPayload):
        raise TypeError("payload must be ResearchReaderPayload")
    if not isinstance(issue, ReaderIssue):
        raise TypeError("issue must be ReaderIssue")
    if not isinstance(candidate, ReaderRepairPatchCandidate):
        raise TypeError("candidate must be ReaderRepairPatchCandidate")
    if not isinstance(application, ReaderRepairApplicationCandidate):
        raise TypeError("application must be ReaderRepairApplicationCandidate")
    if not isinstance(observation, ReaderRepairApplicationObservationCandidate):
        raise TypeError(
            "observation must be ReaderRepairApplicationObservationCandidate"
        )

    before_checksum = checksum_for(payload.to_dict())
    after_checksum = checksum_for(application.after_payload.to_dict())
    candidate_checksum = checksum_for(candidate.to_dict())
    application_checksum = checksum_for(application.to_dict())
    observation_checksum = checksum_for(observation.to_dict())
    expected_application: ReaderRepairApplicationCandidate | None = None
    application_error: ReaderRepairApplicationError | None = None
    try:
        expected_application = apply_reader_repair_candidate(
            payload=payload,
            candidate=candidate,
        )
    except ReaderRepairApplicationError as exc:
        application_error = exc

    expected_operation_ids = [
        operation.operation_id for operation in candidate.patch_operations
    ]
    candidate_bound = bool(
        application.candidate_id == candidate.candidate_id
        and application.applied_operation_ids == expected_operation_ids
        and set(application.target_region_refs) == set(candidate.target_region_refs)
        and set(application.source_refs) == set(candidate.target_region_refs)
        and application.input_bindings.get("reader_repair_patch_candidate")
        == candidate_checksum
    )
    application_bound = bool(
        expected_application is not None
        and application.to_dict() == expected_application.to_dict()
    )
    observed_refs = {
        *observation.source_refs,
        *(
            ref
            for item in observation.observations
            for ref in item.evidence_refs
        ),
    }
    observation_bound = bool(
        observation.candidate_id == candidate.candidate_id
        and observation.application_id == application.application_id
        and observation.input_bindings
        == {
            "reader_repair_patch_candidate": candidate_checksum,
            "reader_repair_application_candidate": application_checksum,
        }
        and set(observation.source_refs) == set(application.source_refs)
        and observed_refs.issubset(set(issue.source_refs))
    )
    paper_identity_bound = bool(
        application.after_payload.payload_id == payload.payload_id
        and application.after_payload.paper == payload.paper
        and application.after_payload.document.paper_id == payload.paper.paper_id
    )
    target_scope_bound = bool(
        issue.payload_ref
        and issue.payload_ref == payload.payload_id
        and set(candidate.target_region_refs).issubset(set(issue.source_refs))
        and all(
            set(operation.source_refs).issubset(set(issue.source_refs))
            for operation in candidate.patch_operations
        )
    )
    schema_result = validate_reader_payload_schema(application.after_payload)
    navigation_result = validate_reader_navigation(application.after_payload)
    lineage_result = validate_reader_source_lineage(application.after_payload)
    allowed_lineage_refs = {
        *payload.source_lineage.source_refs,
        *issue.source_refs,
    }
    before_projection = payload.to_dict()
    after_projection = application.after_payload.to_dict()
    introduced_source_refs = sorted(
        _collect_named_refs(
            after_projection,
            keys={"source_ref", "source_refs"},
        )
        - {
            *_collect_named_refs(
                before_projection,
                keys={"source_ref", "source_refs"},
            ),
            *issue.source_refs,
        }
    )
    artifact_lineage_changed = bool(
        _collect_named_refs(after_projection, keys={"artifact_refs"})
        != _collect_named_refs(before_projection, keys={"artifact_refs"})
    )
    source_identity_changed = bool(
        application.after_payload.document.source_hash
        != payload.document.source_hash
    )
    lineage_bound = bool(
        lineage_result.passed
        and set(application.after_payload.source_lineage.source_refs).issubset(
            allowed_lineage_refs
        )
        and not introduced_source_refs
        and not artifact_lineage_changed
        and not source_identity_changed
    )

    checks = [
        _check(
            "candidate_binding",
            candidate_bound,
            evidence_refs=[candidate_checksum],
        ),
        _check(
            "application_binding",
            application_bound,
            actual=(application_error.code if application_error else None),
            evidence_refs=[application.after_payload_checksum],
        ),
        _check(
            "observation_binding",
            observation_bound,
            evidence_refs=[observation_checksum, *observation.source_refs],
        ),
        _check(
            "before_checksum",
            application.before_payload_checksum == before_checksum,
            actual=application.before_payload_checksum,
            expected=before_checksum,
            evidence_refs=[before_checksum],
        ),
        _check(
            "after_checksum",
            application.after_payload_checksum == after_checksum,
            actual=application.after_payload_checksum,
            expected=after_checksum,
            evidence_refs=[after_checksum],
        ),
        _check(
            "payload_changed",
            before_checksum != after_checksum,
            evidence_refs=[before_checksum, after_checksum],
        ),
        _check(
            "paper_identity",
            paper_identity_bound,
            evidence_refs=[checksum_for(payload.paper.to_dict())],
        ),
        _check(
            "target_scope",
            target_scope_bound,
            evidence_refs=issue.source_refs,
        ),
        _check(
            "reader_schema",
            schema_result.passed,
            actual=_gate_actual(schema_result.passed, schema_result.reasons),
            evidence_refs=[after_checksum],
        ),
        _check(
            "reader_navigation",
            navigation_result.passed,
            actual=_gate_actual(
                navigation_result.passed,
                navigation_result.reasons,
            ),
            evidence_refs=[after_checksum],
        ),
        _check(
            "source_lineage",
            lineage_bound,
            actual=_lineage_actual(
                passed=lineage_bound,
                gate_reasons=lineage_result.reasons,
                introduced_source_refs=introduced_source_refs,
                artifact_lineage_changed=artifact_lineage_changed,
                source_identity_changed=source_identity_changed,
            ),
            evidence_refs=application.after_payload.source_lineage.source_refs,
        ),
    ]
    verification_checksum = checksum_for([item.to_dict() for item in checks])
    return ReaderRepairApplicationVerificationRecord(
        verification_id=stable_research_id(
            "reader_repair_application_verification",
            application.application_id,
            verification_checksum,
        ),
        application_id=application.application_id,
        candidate_id=candidate.candidate_id,
        observation_candidate_checksum=observation_checksum,
        before_payload_checksum=before_checksum,
        after_payload_checksum=after_checksum,
        checks=checks,
        successful=all(item.passed for item in checks),
        source_refs=application.source_refs,
    )


def _component_projection(
    payload: ResearchReaderPayload,
    target: str,
) -> Any:
    value = getattr(payload, target)
    if isinstance(value, list):
        return [item.to_dict() for item in value]
    if value is None:
        return None
    return value.to_dict()


def _operation_replacement(operation: ReaderRepairPatchOperationBase) -> Any:
    if isinstance(
        operation,
        ReaderRepairRemoveAnalysisOperation | ReaderRepairRemoveEvidenceOperation,
    ):
        return None
    if isinstance(
        operation,
        ReaderRepairReplaceDocumentOperation
        | ReaderRepairReplaceAnalysisOperation
        | ReaderRepairReplaceEvidenceOperation
        | ReaderRepairReplaceSourceLineageOperation,
    ):
        return operation.replacement.to_dict()
    if isinstance(
        operation,
        ReaderRepairReplaceNavigationOperation
        | ReaderRepairReplaceAnnotationsOperation
        | ReaderRepairReplaceQualityOperation,
    ):
        return [item.to_dict() for item in operation.replacement]
    raise TypeError("unsupported reader repair patch operation")


def _check(
    check_id: str,
    passed: bool,
    *,
    expected: str | None = None,
    actual: str | None = None,
    evidence_refs: list[str] | None = None,
) -> ReaderRepairApplicationCheck:
    return ReaderRepairApplicationCheck(
        check_id=check_id,
        passed=passed,
        expected=expected or "satisfied",
        actual=actual or ("satisfied" if passed else "not_satisfied"),
        evidence_refs=evidence_refs or [],
    )


def _gate_actual(passed: bool, reasons: list[str]) -> str:
    if passed:
        return "satisfied"
    return "; ".join(reasons) or "not_satisfied"


def _lineage_actual(
    *,
    passed: bool,
    gate_reasons: list[str],
    introduced_source_refs: list[str],
    artifact_lineage_changed: bool,
    source_identity_changed: bool,
) -> str:
    if passed:
        return "satisfied"
    reasons = list(gate_reasons)
    if introduced_source_refs:
        reasons.append("undeclared_source_refs")
    if artifact_lineage_changed:
        reasons.append("artifact_lineage_changed")
    if source_identity_changed:
        reasons.append("source_identity_changed")
    return "; ".join(reasons) or "not_satisfied"


def _collect_named_refs(value: Any, *, keys: set[str]) -> set[str]:
    refs: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                if str(key) in keys:
                    if isinstance(item, str) and item.strip():
                        refs.add(item.strip())
                    elif isinstance(item, list):
                        refs.update(
                            str(ref).strip()
                            for ref in item
                            if isinstance(ref, str) and ref.strip()
                        )
                pending.append(item)
        elif isinstance(current, list):
            pending.extend(current)
    return refs


__all__ = [
    "ReaderRepairApplicationError",
    "apply_reader_repair_candidate",
    "reader_repair_component_checksum",
    "verify_reader_repair_application",
]
