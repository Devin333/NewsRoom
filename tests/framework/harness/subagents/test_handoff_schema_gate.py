from __future__ import annotations

import pytest

from framework.harness import HarnessValidationError, SubAgentHandoff
from framework.harness.subagents import verify_handoff


def test_handoff_payload_must_match_schema() -> None:
    handoff = SubAgentHandoff(
        handoff_id="handoff-1",
        from_subagent_id="author",
        to_subagent_id="critic",
        parent_run_id="run-1",
        payload={"claim": "structured"},
        payload_schema={"required": ["claim"], "properties": {"claim": {"type": "string"}}},
    )

    assert verify_handoff(handoff).passed is True


def test_handoff_schema_gate_rejects_missing_required_payload() -> None:
    handoff = SubAgentHandoff(
        handoff_id="handoff-2",
        from_subagent_id="author",
        to_subagent_id="critic",
        parent_run_id="run-1",
        payload={"summary": "wrong field"},
        payload_schema={"required": ["claim"]},
    )

    result = verify_handoff(handoff)

    assert result.passed is False
    assert result.details["missing"] == ["claim"]


def test_handoff_rejects_private_notes() -> None:
    with pytest.raises(HarnessValidationError):
        SubAgentHandoff(
            handoff_id="handoff-3",
            from_subagent_id="author",
            to_subagent_id="critic",
            parent_run_id="run-1",
            payload={"sibling_private_notes": ["private"]},
            payload_schema={"required": ["sibling_private_notes"]},
        )
