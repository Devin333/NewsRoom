from __future__ import annotations

import json

import pytest

from framework.agent.models.orchestration import ParentObservationLimits
from framework.events.canonical import checksum_for
from framework.harness.agent_loop.orchestration import (
    ParentObservationLimits as AgentLoopObservationLimits,
)
from framework.harness.task_plan.parallel import (
    ParentObservationLimits as TaskPlanObservationLimits,
)


DEFAULT_LIMITS = {
    "max_task_summaries": 8,
    "max_summary_bytes": 2048,
    "max_diagnostics": 16,
    "max_refs": 16,
    "max_observation_bytes": 16384,
}


def test_agent_and_harness_share_one_canonical_observation_limit_contract() -> None:
    assert AgentLoopObservationLimits is ParentObservationLimits
    assert TaskPlanObservationLimits is ParentObservationLimits
    assert ParentObservationLimits().to_dict() == DEFAULT_LIMITS


def test_observation_limits_roundtrip_preserves_values_and_checksum() -> None:
    payload = {name: value + 1 for name, value in DEFAULT_LIMITS.items()}
    agent = ParentObservationLimits.from_dict(payload)
    encoded = json.dumps(agent.to_dict(), sort_keys=True)
    harness = TaskPlanObservationLimits.from_dict(json.loads(encoded))

    assert harness == agent
    assert harness.to_dict() == payload
    assert checksum_for(harness.to_dict()) == checksum_for(payload)
    assert "max_total_bytes" not in encoded


@pytest.mark.parametrize("field", tuple(DEFAULT_LIMITS))
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "2", None])
def test_observation_limit_fields_require_positive_non_boolean_integers(
    field: str, value: object,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ParentObservationLimits.from_dict({**DEFAULT_LIMITS, field: value})


@pytest.mark.parametrize("field", ["max_total_bytes", "max_observaton_bytes", "extra"])
def test_observation_limit_contract_rejects_legacy_and_unknown_fields(field: str) -> None:
    with pytest.raises(ValueError, match="unknown fields"):
        ParentObservationLimits.from_dict({**DEFAULT_LIMITS, field: 512})


@pytest.mark.parametrize("field", tuple(DEFAULT_LIMITS))
def test_serialized_observation_limits_cannot_silently_omit_a_field(field: str) -> None:
    payload = dict(DEFAULT_LIMITS)
    del payload[field]

    with pytest.raises(ValueError, match="missing fields"):
        ParentObservationLimits.from_dict(payload)
