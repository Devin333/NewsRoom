from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from framework.events.canonical import checksum_for

from business.research.domain import (
    READER_REPAIR_APPLICATION_CHECK_IDS,
    ReaderIssue,
    ReaderNavigationItem,
    ReaderRepairApplicationCandidate,
    ReaderRepairApplicationObservationCandidate,
    ReaderRepairPatchCandidate,
    ResearchDocument,
    ResearchSection,
    SourceLineage,
    stable_research_id,
)
from business.research.reader import ReaderPayloadBuilder
from business.research.reader_repair import (
    ReaderRepairApplicationError,
    apply_reader_repair_candidate,
    reader_repair_component_checksum,
    verify_reader_repair_application,
)
from tests.business.research.fakes import FakeResearchSourceProvider


SOURCE_REF = "paper://paper-harness-001/raw"


def test_apply_reader_repair_candidate_returns_checksum_bound_payload_candidate() -> None:
    payload = _repairable_payload()
    candidate = _valid_candidate(payload)

    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )

    assert application.candidate_id == candidate.candidate_id
    assert application.before_payload_checksum == checksum_for(payload.to_dict())
    assert application.after_payload_checksum == checksum_for(
        application.after_payload.to_dict()
    )
    assert application.after_payload.status == "pending"
    assert application.after_payload.document.sections[0].section_id == "section-1"
    assert application.after_payload.navigation[0].target_ref == "section-1"
    assert application.applied_operation_ids == [
        "replace-document",
        "replace-navigation",
    ]
    assert application.input_bindings == {
        "reader_payload": checksum_for(payload.to_dict()),
        "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
    }
    assert "payload_after_ref" not in application.to_dict()
    assert "public_ref" not in application.to_dict()


def test_verify_reader_repair_application_recomputes_all_checks() -> None:
    payload = _repairable_payload()
    candidate = _valid_candidate(payload)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )

    record = verify_reader_repair_application(
        payload=payload,
        issue=_issue(payload),
        candidate=candidate,
        application=application,
        observation=_observation(candidate, application),
    )

    assert record.successful is True
    assert tuple(item.check_id for item in record.checks) == (
        READER_REPAIR_APPLICATION_CHECK_IDS
    )
    assert all(item.passed for item in record.checks)
    assert record.before_payload_checksum == checksum_for(payload.to_dict())
    assert record.after_payload_checksum == application.after_payload_checksum


def test_reader_repair_patch_schema_rejects_open_or_unbounded_operations() -> None:
    payload = _repairable_payload()
    raw_candidate = _valid_candidate(payload).to_dict()
    raw_candidate["patch_operations"] = [
        {
            "op": "replace_region",
            "operation_id": "open-json-patch",
            "path": "/document/sections/0",
            "expected_before_checksum": checksum_for(None),
            "source_refs": [SOURCE_REF],
        }
    ]
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        ReaderRepairPatchCandidate.model_validate(raw_candidate)

    operation = _valid_candidate(payload).patch_operations[0].to_dict()
    raw_candidate["patch_operations"] = [
        {**operation, "operation_id": f"operation-{index}"}
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="operation budget"):
        ReaderRepairPatchCandidate.model_validate(raw_candidate)


def test_reader_repair_patch_candidate_rejects_decision_authority() -> None:
    payload = _repairable_payload()
    raw_candidate = _valid_candidate(payload).to_dict()
    raw_candidate["metadata"] = {"publish_artifact": True}

    with pytest.raises(ValueError, match="forbidden flow-control"):
        ReaderRepairPatchCandidate.model_validate(raw_candidate)


def test_application_observation_candidate_rejects_worker_verdict() -> None:
    payload = _repairable_payload()
    candidate = _valid_candidate(payload)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    raw_observation = _observation(candidate, application).to_dict()
    raw_observation["observations"][0]["metadata"] = {"passed": True}

    with pytest.raises(ValueError, match="decision fields"):
        ReaderRepairApplicationObservationCandidate.model_validate(raw_observation)


def test_apply_reader_repair_candidate_fails_closed_on_stale_checksum() -> None:
    payload = _repairable_payload()
    raw_candidate = _valid_candidate(payload).to_dict()
    raw_candidate["patch_operations"][0]["expected_before_checksum"] = checksum_for(
        {"stale": True}
    )
    candidate = ReaderRepairPatchCandidate.model_validate(raw_candidate)

    with pytest.raises(ReaderRepairApplicationError) as raised:
        apply_reader_repair_candidate(payload=payload, candidate=candidate)

    assert raised.value.code == "reader_repair_patch_before_checksum_mismatch"
    assert raised.value.details["target"] == "document"


def test_apply_reader_repair_candidate_rejects_no_effect_patch() -> None:
    payload = _repairable_payload()
    candidate = ReaderRepairPatchCandidate(
        candidate_id="candidate-no-effect",
        repair_summary="Keep the existing navigation.",
        target_region_refs=[SOURCE_REF],
        patch_operations=[
            {
                "op": "replace_navigation",
                "operation_id": "replace-navigation",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "navigation",
                ),
                "source_refs": [SOURCE_REF],
                "replacement": payload.navigation,
            }
        ],
        expected_effect="No effective change.",
    )

    with pytest.raises(ReaderRepairApplicationError) as raised:
        apply_reader_repair_candidate(payload=payload, candidate=candidate)

    assert raised.value.code == "reader_repair_patch_no_effect"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        pytest.param(
            lambda operation: operation["replacement"]["sections"][0].update(
                {"source_ref": "paper://outside/raw"}
            ),
            "reader_repair_patch_source_scope_expanded",
            id="undeclared-source-ref",
        ),
        pytest.param(
            lambda operation: operation["replacement"]["lineage"].update(
                {"artifact_refs": ["artifact://untrusted-reader-payload"]}
            ),
            "reader_repair_patch_artifact_lineage_changed",
            id="artifact-lineage-authority",
        ),
    ),
)
def test_apply_reader_repair_candidate_rejects_lineage_authority_expansion(
    mutate,
    expected_code: str,
) -> None:
    payload = _repairable_payload()
    raw_candidate = _valid_candidate(payload).to_dict()
    mutate(raw_candidate["patch_operations"][0])
    candidate = ReaderRepairPatchCandidate.model_validate(raw_candidate)

    with pytest.raises(ReaderRepairApplicationError) as raised:
        apply_reader_repair_candidate(payload=payload, candidate=candidate)

    assert raised.value.code == expected_code


def test_verification_rejects_tampered_application_payload() -> None:
    payload = _repairable_payload()
    candidate = _valid_candidate(payload)
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )
    tampered = application.to_dict()
    tampered["after_payload"]["navigation"] = []
    tampered["after_payload_checksum"] = checksum_for(tampered["after_payload"])
    tampered_application = ReaderRepairApplicationCandidate.model_validate(tampered)

    record = verify_reader_repair_application(
        payload=payload,
        issue=_issue(payload),
        candidate=candidate,
        application=tampered_application,
        observation=_observation(candidate, tampered_application),
    )

    failed = {item.check_id for item in record.checks if not item.passed}
    assert record.successful is False
    assert {"application_binding", "reader_navigation"}.issubset(failed)


def test_verification_rejects_candidate_outside_issue_scope() -> None:
    payload = _repairable_payload()
    candidate = _valid_candidate(payload, source_ref="paper://other/raw")
    application = apply_reader_repair_candidate(
        payload=payload,
        candidate=candidate,
    )

    record = verify_reader_repair_application(
        payload=payload,
        issue=_issue(payload),
        candidate=candidate,
        application=application,
        observation=_observation(candidate, application),
    )

    assert record.successful is False
    assert next(
        item for item in record.checks if item.check_id == "target_scope"
    ).passed is False


def test_reader_repair_application_module_has_no_side_effect_owner_imports() -> None:
    module_path = Path(
        "business/research/reader_repair/application.py"
    )
    source = module_path.read_text(encoding="utf-8").casefold()

    assert "framework.harness.artifacts" not in source
    assert "artifactport" not in source
    assert "artifact_publication" not in source
    assert "memory" not in source
    assert "storage" not in source
    assert "store" not in source


def _repairable_payload():
    paper = FakeResearchSourceProvider().paper
    document = ResearchDocument(
        paper_id=paper.paper_id,
        source_hash="sha256-reader-repair-v2",
        sections=[],
        lineage=SourceLineage(source_refs=[SOURCE_REF]),
    )
    return ReaderPayloadBuilder().build(paper=paper, document=document)


def _valid_candidate(
    payload,
    *,
    source_ref: str = SOURCE_REF,
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
        candidate_id="reader-repair-patch-1",
        repair_summary="Restore the source-backed section and navigation.",
        target_region_refs=[source_ref],
        patch_operations=[
            {
                "op": "replace_document",
                "operation_id": "replace-document",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "document",
                ),
                "source_refs": [source_ref],
                "replacement": document,
            },
            {
                "op": "replace_navigation",
                "operation_id": "replace-navigation",
                "expected_before_checksum": reader_repair_component_checksum(
                    payload,
                    "navigation",
                ),
                "source_refs": [source_ref],
                "replacement": [navigation],
            },
        ],
        expected_effect="Reader navigation matches the repaired document.",
        risks=["section offsets may change"],
        confidence=0.9,
    )


def _issue(payload) -> ReaderIssue:
    return ReaderIssue(
        issue_id="reader-issue-v2",
        paper_id=payload.paper.paper_id,
        run_id="reader-repair-v2-run",
        step_id="build_reader_payload",
        issue_type="section_boundary_error",
        severity="high",
        error_signature="section-boundary:missing",
        symptom="Reader document and navigation have no sections.",
        source_refs=[SOURCE_REF],
        payload_ref=payload.payload_id,
    )


def _observation(
    candidate: ReaderRepairPatchCandidate,
    application: ReaderRepairApplicationCandidate,
) -> ReaderRepairApplicationObservationCandidate:
    return ReaderRepairApplicationObservationCandidate(
        candidate_id=candidate.candidate_id,
        application_id=application.application_id,
        observations=[
            {
                "check_id": "source-backed-application",
                "finding": "The application remains bound to the source region.",
                "evidence_refs": application.source_refs,
            }
        ],
        source_refs=application.source_refs,
        input_bindings={
            "reader_repair_patch_candidate": checksum_for(candidate.to_dict()),
            "reader_repair_application_candidate": checksum_for(
                application.to_dict()
            ),
        },
    )
