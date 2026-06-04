from __future__ import annotations

from framework.harness import InMemorySkillCandidateStore, SkillCandidate, SkillCandidateStatus, SkillPatchSet, SkillVersionRef


def test_candidate_store_saves_rejected_candidates_in_rejected_buffer() -> None:
    store = InMemorySkillCandidateStore()
    candidate = _candidate("candidate-rejected")

    rejected = store.save_rejected(candidate, "held-out eval failed")

    assert rejected.status == SkillCandidateStatus.REJECTED
    assert store.list_rejected({"skill_name": "reader.repair"}) == (rejected,)


def test_candidate_store_filters_by_status_and_skill_name() -> None:
    store = InMemorySkillCandidateStore()
    candidate = _candidate("candidate-1")
    store.save_candidate(candidate)

    assert store.get_candidate("candidate-1") == candidate
    assert store.list_candidates({"skill_name": "reader.repair"}) == (candidate,)
    assert store.list_candidates({"status": "proposed"}) == (candidate,)


def _candidate(candidate_id: str) -> SkillCandidate:
    base = SkillVersionRef(skill_name="reader.repair", version="1.0.0")
    return SkillCandidate(
        candidate_id=candidate_id,
        base_version=base,
        patch_set=SkillPatchSet(
            candidate_id=candidate_id,
            base_skill=base,
            operations=({"op": "replace_section", "path": "SKILL.md#repair", "value": "preserve refs"},),
        ),
    )
