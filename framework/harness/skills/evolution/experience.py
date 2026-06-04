from __future__ import annotations

from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.models import (
    SkillExperience,
    SkillExperienceOutcome,
    SkillExperiencePool,
)


class InMemorySkillExperienceStore:
    def __init__(self) -> None:
        self.experiences: dict[str, SkillExperience] = {}

    def append_experience(self, experience: SkillExperience) -> SkillExperience:
        self.experiences[experience.experience_id] = experience
        return experience

    def query_experiences(self, request: dict[str, Any]) -> tuple[SkillExperience, ...]:
        skill_name = request.get("skill_name")
        domain = request.get("domain")
        task_type = request.get("task_type")
        outcome = request.get("outcome")
        failure_tags = set(request.get("failure_tags", ()))
        limit = int(request.get("limit", len(self.experiences) or 1))
        results = []
        for experience in sorted(self.experiences.values(), key=lambda item: item.experience_id):
            if skill_name and experience.skill_name != skill_name:
                continue
            if domain and experience.domain != domain:
                continue
            if task_type and experience.task_type != task_type:
                continue
            if outcome and experience.outcome != SkillExperienceOutcome(outcome):
                continue
            if failure_tags and not failure_tags.intersection(experience.failure_tags):
                continue
            results.append(experience)
        return tuple(results[:limit])

    def build_pool(self, request: dict[str, Any]) -> SkillExperiencePool:
        skill_name = str(request.get("skill_name", "")).strip()
        if not skill_name:
            raise HarnessValidationError("skill_name is required to build experience pool")
        max_pool_size = int(request.get("max_pool_size", 8))
        held_out_split = float(request.get("held_out_split", 0.25))
        experiences = self.query_experiences({**request, "limit": max_pool_size})
        if not experiences:
            raise HarnessValidationError("experience pool cannot be empty")
        success = [item for item in experiences if item.outcome == SkillExperienceOutcome.SUCCESS]
        failure = [item for item in experiences if item.outcome == SkillExperienceOutcome.FAILURE]
        if request.get("require_success_and_failure", True) and (not success or not failure):
            raise HarnessValidationError("experience pool requires both successful and failed experiences")
        held_out_count = max(1, int(len(experiences) * held_out_split)) if len(experiences) > 1 else 0
        held_out_ids = tuple(item.experience_id for item in experiences[-held_out_count:]) if held_out_count else ()
        return SkillExperiencePool(
            pool_id=str(request.get("pool_id", f"skill-experience-pool://{skill_name}/{len(experiences)}")),
            skill_name=skill_name,
            experiences=experiences,
            held_out_experience_ids=held_out_ids,
            selection_policy={
                "max_pool_size": max_pool_size,
                "held_out_split": held_out_split,
                "require_success_and_failure": request.get("require_success_and_failure", True),
            },
        )


__all__ = ["InMemorySkillExperienceStore"]
