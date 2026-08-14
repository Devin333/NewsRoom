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


def test_handoff_rejects_nested_private_notes() -> None:
    with pytest.raises(HarnessValidationError):
        SubAgentHandoff(
            handoff_id="handoff-4",
            from_subagent_id="author",
            to_subagent_id="critic",
            parent_run_id="run-1",
            payload={"nested": {"sibling_private_notes": ["private"]}},
            payload_schema={"required": ["nested"]},
        )


@pytest.mark.parametrize("field_name", ["input_refs", "artifact_refs"])
def test_handoff_rejects_string_reference_collections(field_name: str) -> None:
    values = {
        "handoff_id": "handoff-5",
        "from_subagent_id": "author",
        "to_subagent_id": "critic",
        "parent_run_id": "run-1",
        "payload": {"claim": "structured"},
        "payload_schema": {"required": ["claim"]},
        field_name: "artifact://research/not-an-array",
    }

    with pytest.raises(HarnessValidationError) as exc_info:
        SubAgentHandoff(**values)

    assert exc_info.value.code == "subagent_handoff_invalid_payload"


def test_handoff_from_dict_wraps_invalid_timestamp() -> None:
    handoff = SubAgentHandoff(
        handoff_id="handoff-6",
        from_subagent_id="author",
        to_subagent_id="critic",
        parent_run_id="run-1",
        payload={"claim": "structured"},
        payload_schema={"required": ["claim"]},
    ).to_dict()
    handoff["created_at"] = "not-a-timestamp"

    with pytest.raises(HarnessValidationError) as exc_info:
        SubAgentHandoff.from_dict(handoff)

    assert exc_info.value.code == "subagent_handoff_invalid_payload"
