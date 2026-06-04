from __future__ import annotations

from framework.harness import (
    SkillEvalReplayRunner,
    SkillPromotionDecider,
    VersionedSkillReleaseRegistry,
)
from tests.framework.harness.skills.evolution.test_static_gates import _candidate


def test_versioned_release_keeps_previous_version_and_can_rollback() -> None:
    candidate = _candidate()
    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {"baseline_score": 0.7, "candidate_score": 0.86, "minimum_improvement": 0.05},
    )
    decision = SkillPromotionDecider().decide(candidate, evaluation, release_version="1.1.0")
    registry = VersionedSkillReleaseRegistry()

    release = registry.prepare_release(candidate, decision)
    registry.publish_release(release)

    assert registry.get_active_version("reader.repair").version == "1.1.0"
    rollback = registry.rollback(release.rollback_plan)
    assert rollback.metadata["rolled_back"] is True
    assert registry.get_active_version("reader.repair").version == "1.0.0"
