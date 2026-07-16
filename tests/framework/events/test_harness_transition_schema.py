from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events.errors import EventSchemaValidationError
from framework.events.schema import default_event_schema_catalog
from framework.harness.control_plane.state import HarnessRunSpec, HarnessState
from framework.harness.control_plane.transition import HarnessTransitionCommitted
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessStepSpec


NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)


def _transition() -> HarnessTransitionCommitted:
    run_spec = HarnessRunSpec(
        run_id="run-schema-transition",
        workflow=HarnessWorkflowSpec(
            workflow_id="schema-transition",
            steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
        created_at=NOW,
    )
    initial = HarnessState.initial(run_spec)
    initial = replace(
        initial,
        updated_at=NOW,
        step_states=tuple(replace(step, updated_at=NOW) for step in initial.step_states),
    )
    return HarnessTransitionCommitted.create(
        previous=None,
        state=initial,
        from_version=0,
        expected_last_sequence=0,
        transition_kind="initialize",
        occurred_at=NOW,
    )


def test_default_catalog_registers_strict_harness_transition_schema() -> None:
    transition = _transition()
    catalog = default_event_schema_catalog()

    assert catalog.current_schema("harness_transition_committed") == (
        "newsroom.harness-transition/v1"
    )
    assert catalog.validate(
        "harness_transition_committed",
        "newsroom.harness-transition/v1",
        transition.to_payload(),
    ) == transition.to_payload()


def test_harness_transition_schema_rejects_raw_recovery_content() -> None:
    payload = _transition().to_payload()
    payload["state"]["metadata"]["outputs"] = {"answer": "raw"}

    with pytest.raises(EventSchemaValidationError) as failure:
        default_event_schema_catalog().validate(
            "harness_transition_committed",
            "newsroom.harness-transition/v1",
            payload,
        )

    assert failure.value.path == "$.state.metadata"
