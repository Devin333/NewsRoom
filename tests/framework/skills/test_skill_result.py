from __future__ import annotations

from framework.skills import SkillFailureReason, SkillResult, SkillRunStatus


def test_skill_result_success_failed_and_mutators() -> None:
    success = SkillResult.success("runnable-skill", "1.0.0", {"result": "ok"})

    assert success.is_success()
    assert success.status == SkillRunStatus.SUCCESS

    success.add_warning("heads_up", "minor warning", {"field": "result"})
    success.add_error("minor_error", "minor error", field="result", path="result")

    assert not success.is_success()
    assert success.warnings[0].detail == {"field": "result"}
    assert success.errors[0].field == "result"

    failed = SkillResult.failed(
        "runnable-skill",
        "1.0.0",
        SkillFailureReason.EXECUTION_FAILED,
        "execution_failed",
        "boom",
    )

    assert failed.status == SkillRunStatus.FAILED
    assert failed.failure_reason == SkillFailureReason.EXECUTION_FAILED
    assert failed.errors[0].message == "boom"
