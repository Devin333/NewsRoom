from __future__ import annotations

import pytest

from framework.shared import RuntimeStatus


def test_runtime_status_helpers() -> None:
    assert RuntimeStatus.SUCCEEDED.is_terminal()
    assert RuntimeStatus.SUCCEEDED.is_success()
    assert not RuntimeStatus.SUCCEEDED.is_failure()
    assert RuntimeStatus.FAILED.is_terminal()
    assert RuntimeStatus.FAILED.is_failure()
    assert not RuntimeStatus.RUNNING.is_terminal()
    assert RuntimeStatus.DEGRADED == RuntimeStatus.from_value("degraded")


def test_runtime_status_from_value_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        RuntimeStatus.from_value("unknown")
