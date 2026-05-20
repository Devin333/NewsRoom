from __future__ import annotations

from typing import Any


class RuntimeStatusClassifier:
    WORKFLOW_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "budget_exceeded"})
    WORKFLOW_RECOVERABLE = frozenset({"blocked", "paused", "waiting_for_human"})
    WORKFLOW_WAITING = frozenset({"paused", "waiting_for_human"})
    WORKFLOW_ACTIVE = frozenset({"created", "running", "retrying"})

    STEP_TERMINAL = frozenset({"succeeded", "failed", "skipped", "cancelled", "timeout"})
    STEP_RETRYABLE = frozenset({"failed", "timeout"})
    STEP_WAITING = frozenset({"blocked", "paused"})
    STEP_ACTIVE = frozenset({"pending", "ready", "running", "retrying"})

    @classmethod
    def is_terminal_workflow(cls, status: Any) -> bool:
        return _status_value(status) in cls.WORKFLOW_TERMINAL

    @classmethod
    def is_recoverable_workflow(cls, status: Any) -> bool:
        return _status_value(status) in cls.WORKFLOW_RECOVERABLE

    @classmethod
    def is_waiting_workflow(cls, status: Any) -> bool:
        return _status_value(status) in cls.WORKFLOW_WAITING

    @classmethod
    def is_active_workflow(cls, status: Any) -> bool:
        return _status_value(status) in cls.WORKFLOW_ACTIVE

    @classmethod
    def is_terminal_step(cls, status: Any) -> bool:
        return _status_value(status) in cls.STEP_TERMINAL

    @classmethod
    def is_retryable_step(cls, status: Any) -> bool:
        return _status_value(status) in cls.STEP_RETRYABLE

    @classmethod
    def is_waiting_step(cls, status: Any) -> bool:
        return _status_value(status) in cls.STEP_WAITING

    @classmethod
    def is_active_step(cls, status: Any) -> bool:
        return _status_value(status) in cls.STEP_ACTIVE


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status))
