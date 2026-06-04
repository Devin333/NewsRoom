from __future__ import annotations

from framework.harness import HarnessValidationError, SkillCandidate, SkillPatchSet, SkillVersionRef


def test_optimizer_candidate_cannot_request_active_or_promote() -> None:
    base = SkillVersionRef(skill_name="reader.repair", version="1.0.0")
    patch = SkillPatchSet(
        candidate_id="candidate-boundary",
        base_skill=base,
        operations=({"op": "replace_section", "path": "SKILL.md#repair", "value": "preserve refs"},),
    )

    try:
        SkillCandidate(
            candidate_id="candidate-boundary",
            base_version=base,
            patch_set=patch,
            metadata={"active": True, "promote": True},
        )
    except HarnessValidationError as exc:
        assert exc.details["forbidden"] == ["active", "promote"]
    else:
        raise AssertionError("expected HarnessValidationError")
