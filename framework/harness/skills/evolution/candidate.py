from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.models import (
    RejectedSkillCandidate,
    SkillCandidate,
    SkillCandidateStatus,
    SkillPatchSet,
    SkillVersionRef,
)


class InMemorySkillCandidateStore:
    def __init__(self) -> None:
        self.candidates: dict[str, SkillCandidate] = {}
        self.rejected: dict[str, RejectedSkillCandidate] = {}

    def save_candidate(self, candidate: SkillCandidate) -> SkillCandidate:
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    def get_candidate(self, candidate_id: str) -> SkillCandidate:
        return self.candidates[candidate_id]

    def list_candidates(self, request: dict[str, Any] | None = None) -> tuple[SkillCandidate, ...]:
        request = request or {}
        status = request.get("status")
        skill_name = request.get("skill_name")
        results = []
        for candidate in sorted(self.candidates.values(), key=lambda item: item.candidate_id):
            if status and candidate.status != SkillCandidateStatus(status):
                continue
            if skill_name and candidate.base_version.skill_name != skill_name:
                continue
            results.append(candidate)
        return tuple(results)

    def save_rejected(self, candidate: SkillCandidate, reason: str) -> SkillCandidate:
        rejected_candidate = replace(candidate, status=SkillCandidateStatus.REJECTED)
        self.candidates[rejected_candidate.candidate_id] = rejected_candidate
        self.rejected[rejected_candidate.candidate_id] = RejectedSkillCandidate(
            candidate=rejected_candidate,
            reason=reason,
        )
        return rejected_candidate

    def list_rejected(self, request: dict[str, Any] | None = None) -> tuple[SkillCandidate, ...]:
        request = request or {}
        skill_name = request.get("skill_name")
        results = []
        for rejected in sorted(self.rejected.values(), key=lambda item: item.candidate.candidate_id):
            if skill_name and rejected.candidate.base_version.skill_name != skill_name:
                continue
            results.append(rejected.candidate)
        return tuple(results)


class SkillPatchApplier:
    def apply_patch(self, patch_set: SkillPatchSet, *, package_snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch_set.base_skill, SkillVersionRef):
            raise HarnessValidationError("patch_set base_skill is required")
        snapshot = {key: value for key, value in package_snapshot.items()}
        changed_files = set(patch_set.changed_files)
        for operation in patch_set.operations:
            changed_files.add(_file_from_path(operation.path))
            if operation.op in {"replace", "replace_section", "add_section", "update_frontmatter_field"}:
                snapshot[operation.path] = operation.value
            elif operation.op == "delete_section":
                snapshot.pop(operation.path, None)
            elif operation.op in {"update_prompt_file", "update_reference_file", "update_schema_file", "update_eval_case"}:
                snapshot[operation.path] = operation.value
            else:
                raise HarnessValidationError("unsupported skill patch operation", details={"operation": operation.op})
        snapshot["_patch"] = patch_set.to_dict()
        snapshot["_changed_files"] = sorted(changed_files)
        return snapshot


def _file_from_path(path: str) -> str:
    normalized = str(path).replace("\\", "/").strip("/")
    if not normalized:
        return "SKILL.md"
    return normalized.split("#", 1)[0].split("/", 1)[0] or "SKILL.md"


__all__ = ["InMemorySkillCandidateStore", "SkillPatchApplier"]
