from __future__ import annotations

from framework.harness import (
    HarnessValidationError,
    SkillCandidate,
    SkillEvolutionBudget,
    SkillExperience,
    SkillExperienceOutcome,
    SkillPatchOperation,
    SkillPatchSet,
    SkillVersionRef,
)
from framework.harness.skills.evolution.models import ensure_jsonable_skill_model


def test_extended_skill_evolution_models_are_serializable() -> None:
    base = SkillVersionRef(
        skill_name="research-reader-repair",
        version="1.0.0",
        package_hash="sha256:base",
        source_root="skills/research-reader-repair",
    )
    experience = SkillExperience(
        experience_id="experience-1",
        run_id="run-1",
        step_id="reader-repair",
        skill_name=base.skill_name,
        skill_version=base.version,
        domain="research",
        task_type="reader_repair",
        transcript_refs=("transcript://run-1",),
        summary="Failed repair lost method paragraph lineage.",
        outcome=SkillExperienceOutcome.FAILURE,
        failure_tags=("missing_lineage",),
        score=0.2,
    )
    patch = SkillPatchSet(
        candidate_id="candidate-1",
        base_skill=base,
        operations=(
            SkillPatchOperation(
                op="replace_section",
                path="SKILL.md#retrieval-strategy",
                value="Preserve source refs before synthesis.",
            ),
        ),
        changed_files=("SKILL.md",),
    )
    candidate = SkillCandidate(
        candidate_id="candidate-1",
        base_version=base,
        candidate_version="1.1.0",
        patch_set=patch,
        experiences=(experience,),
        manifest_snapshot={"files": ["SKILL.md"], "metadata": {"name": base.skill_name, "version": base.version}},
    )

    ensure_jsonable_skill_model({"candidate": candidate, "budget": SkillEvolutionBudget()})

    assert candidate.to_dict()["base_version"]["immutable_ref"].startswith("skill://research-reader-repair@1.0.0")


def test_skill_patch_set_rejects_forbidden_operations() -> None:
    base = SkillVersionRef(skill_name="reader", version="1.0.0")

    try:
        SkillPatchSet(
            candidate_id="candidate-bad",
            base_skill=base,
            operations=({"op": "delete_package", "path": "skills/reader"},),
        )
    except HarnessValidationError as exc:
        assert exc.details["forbidden"] == ["delete_package"]
    else:
        raise AssertionError("expected HarnessValidationError")
