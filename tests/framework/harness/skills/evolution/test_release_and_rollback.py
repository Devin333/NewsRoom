from __future__ import annotations

import pytest

from framework.harness import (
    HarnessValidationError,
    SkillEvalReplayRunner,
    SkillPromotionDecider,
    SkillReleaseAuthorization,
    VersionedSkillReleaseRegistry,
)
from tests.framework.harness.skills.evolution._authority_fixtures import (
    authorized_release_fixture,
)
from tests.framework.harness.skills.evolution.test_static_gates import _candidate


def test_versioned_release_keeps_previous_version_and_can_rollback() -> None:
    fixture = authorized_release_fixture()
    registry = fixture.registry
    release = registry.publish_release(fixture.release)

    assert registry.get_active_version("reader.repair").version == "1.1.0"
    rollback = registry.rollback(release.rollback_plan)
    assert rollback.metadata["rolled_back"] is True
    assert registry.get_active_version("reader.repair").version == "1.0.0"
    assert SkillReleaseAuthorization.from_dict(fixture.authority.to_dict()) == fixture.authority


def test_authorized_release_publication_is_idempotent() -> None:
    fixture = authorized_release_fixture()

    first = fixture.registry.publish_release(fixture.release)
    second = fixture.registry.publish_release(fixture.release)

    assert first == second
    assert fixture.registry.release_write_count == 1
    assert fixture.registry.history_write_count == 1
    assert fixture.registry.active_version_write_count == 1


def test_unbound_release_cannot_mutate_registry_state() -> None:
    candidate = _candidate()
    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {"baseline_score": 0.7, "candidate_score": 0.86, "minimum_improvement": 0.05},
    )
    decision = SkillPromotionDecider().decide(candidate, evaluation, release_version="1.1.0")
    registry = VersionedSkillReleaseRegistry()
    release = registry.prepare_release(candidate, decision)

    with pytest.raises(HarnessValidationError):
        registry.publish_release(release)

    assert registry.releases == {}
    assert registry.version_history == {}
    assert registry.active_versions == {}
