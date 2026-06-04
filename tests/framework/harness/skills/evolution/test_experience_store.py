from __future__ import annotations

from framework.harness import InMemorySkillExperienceStore, SkillExperience, SkillExperienceOutcome


def test_experience_store_builds_pool_with_success_and_failure_held_out_split() -> None:
    store = InMemorySkillExperienceStore()
    store.append_experience(
        SkillExperience(
            experience_id="exp-success",
            skill_name="reader.repair",
            domain="research",
            task_type="reader_repair",
            summary="Reader repair preserved citation refs.",
            outcome=SkillExperienceOutcome.SUCCESS,
            score=0.9,
        )
    )
    store.append_experience(
        SkillExperience(
            experience_id="exp-failure",
            skill_name="reader.repair",
            domain="research",
            task_type="reader_repair",
            summary="Reader repair failed because method lineage was missing.",
            outcome=SkillExperienceOutcome.FAILURE,
            failure_tags=("missing_lineage",),
            score=0.2,
        )
    )

    pool = store.build_pool({"skill_name": "reader.repair", "held_out_split": 0.5})

    assert len(pool.experiences) == 2
    assert pool.held_out_experience_ids == ("exp-success",)


def test_experience_store_requires_failure_examples_by_default() -> None:
    store = InMemorySkillExperienceStore()
    store.append_experience(
        SkillExperience(
            experience_id="exp-success-only",
            skill_name="reader.repair",
            summary="Reader repair succeeded.",
            outcome=SkillExperienceOutcome.SUCCESS,
        )
    )

    try:
        store.build_pool({"skill_name": "reader.repair"})
    except Exception as exc:
        assert exc.__class__.__name__ == "HarnessValidationError"
    else:
        raise AssertionError("expected HarnessValidationError")
