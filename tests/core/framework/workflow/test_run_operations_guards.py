from __future__ import annotations

from core.framework.workflow.operations import RunOperationGuard


def test_succeeded_run_cannot_resume_with_patch() -> None:
    result = RunOperationGuard().can_resume_with_patch("succeeded")

    assert result.allowed is False
    assert result.status == "succeeded"


def test_succeeded_run_can_rerun_from_step() -> None:
    result = RunOperationGuard().can_rerun_from_step("succeeded")

    assert result.allowed is True


def test_running_run_can_cancel() -> None:
    result = RunOperationGuard().can_cancel("running")

    assert result.allowed is True


def test_cancelled_run_cannot_resume() -> None:
    result = RunOperationGuard().can_resume_with_patch("cancelled")

    assert result.allowed is False
    assert result.status == "cancelled"


def test_blocked_run_can_mark_blocked_resolved() -> None:
    result = RunOperationGuard().can_mark_blocked_resolved("blocked")

    assert result.allowed is True


def test_failed_run_can_rerun_from_step() -> None:
    result = RunOperationGuard().can_rerun_from_step("failed")

    assert result.allowed is True
