from __future__ import annotations

import pytest

from framework.harness import HarnessPhase, HarnessPhaseRecord, HarnessValidationError
from framework.harness.control_plane.phase import assert_step_completion_allowed


def test_phase_cannot_complete_without_verify_gate() -> None:
    plan_phase = HarnessPhaseRecord(phase=HarnessPhase.PLAN, node_id="collect")

    with pytest.raises(HarnessValidationError):
        assert_step_completion_allowed(plan_phase)


def test_verify_phase_with_gate_can_complete_step() -> None:
    verify_phase = HarnessPhaseRecord(
        phase=HarnessPhase.VERIFY,
        node_id="collect",
        gate_results=({"gate": "schema", "passed": True},),
    )

    assert_step_completion_allowed(verify_phase)
