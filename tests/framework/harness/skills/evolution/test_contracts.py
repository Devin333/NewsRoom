from __future__ import annotations

import pytest

from framework.harness import (
    HarnessValidationError,
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperience,
    SkillPatchSet,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
    SkillVersionRef,
)


def test_skill_candidate_is_serializable_and_inactive() -> None:
    candidate = _candidate()

    payload = candidate.to_dict()

    assert payload["status"] == "proposed"
    assert "active" not in payload["metadata"]
    assert "auto_promote" not in payload["metadata"]
    assert "skip_eval" not in payload["metadata"]


@pytest.mark.parametrize("bypass_key", ["auto_promote", "active", "skip_eval"])
def test_skill_candidate_rejects_publication_bypass_fields(bypass_key: str) -> None:
    with pytest.raises(HarnessValidationError):
        _candidate(metadata={bypass_key: True})


def test_skill_promotion_decision_must_be_harness_owned() -> None:
    decision = SkillPromotionDecision(
        candidate_id="candidate-1",
        status="approved",
        reasons=("eval passed",),
        required_release_version="1.1.0",
    )
    assert decision.to_dict()["decided_by"] == "harness"

    with pytest.raises(HarnessValidationError):
        SkillPromotionDecision(candidate_id="candidate-1", status="approved", decided_by="llm")


def test_evaluation_release_and_rollback_are_serializable() -> None:
    candidate = _candidate()
    evaluation = SkillEvaluationResult(
        candidate_id=candidate.candidate_id,
        passed=True,
        score=0.91,
        eval_case_count=3,
    )
    rollback = SkillRollbackPlan(
        release_id="release-1",
        previous_version=candidate.base_version,
        triggers=("quality_gate_failed",),
    )
    release = SkillRelease(
        release_id="release-1",
        candidate_id=candidate.candidate_id,
        version=SkillVersionRef(skill_id="reader", version="1.1.0"),
        rollback_plan=rollback,
    )

    assert evaluation.to_dict()["passed"] is True
    assert rollback.to_dict()["fallback_action"] == "halt_skill_use"
    assert release.to_dict()["rollback_plan"]["previous_version"]["version"] == "1.0.0"


def _candidate(metadata: dict[str, object] | None = None) -> SkillCandidate:
    base = SkillVersionRef(skill_id="reader", version="1.0.0", package_ref="skills/reader")
    patch = SkillPatchSet(
        patch_id="patch-1",
        target=base,
        operations=({"op": "replace", "path": "SKILL.md", "value": "new instructions"},),
    )
    experience = SkillExperience(
        experience_id="exp-1",
        source="reader_repair",
        summary="Repair strategy stabilized across malformed PDFs.",
        evidence_refs=("memory://exp-1",),
    )
    return SkillCandidate(
        candidate_id="candidate-1",
        base_version=base,
        patch_set=patch,
        experiences=(experience,),
        metadata=metadata or {},
    )
