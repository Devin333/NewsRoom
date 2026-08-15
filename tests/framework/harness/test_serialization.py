from __future__ import annotations

import pytest

from framework.harness import (
    DeterministicGateRegistry,
    GateBinding,
    GateReference,
    GateRegistration,
    HarnessCheckpoint,
    HarnessDecision,
    HarnessEvent,
    HarnessPhase,
    HarnessPhaseRecord,
    HarnessQualityVerdict,
    HarnessRunSpec,
    HarnessState,
    HarnessStepSpec,
    HarnessTrace,
    HarnessValidationError,
    HarnessWorkerResult,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec


def test_core_contracts_are_serializable() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="research",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm", output_key="candidate"),),
        entry_step_id="collect",
    )
    run_spec = HarnessRunSpec(run_id="run-1", workflow=workflow, inputs={"paper_id": "p1"})
    state = HarnessState.initial(run_spec)
    event = HarnessEvent(event_type="run_created", run_id="run-1", payload={"ok": True})
    trace = HarnessTrace(run_id="run-1").append(event)
    checkpoint = HarnessCheckpoint(checkpoint_id="cp-1", run_id="run-1", state=state)

    payloads = [
        workflow.to_dict(),
        run_spec.to_dict(),
        state.to_dict(),
        HarnessDecision(decision_type="plan_step", run_id="run-1", step_id="collect").to_dict(),
        HarnessPhaseRecord(
            phase=HarnessPhase.VERIFY,
            step_id="collect",
            gate_results=({"gate": "schema", "passed": True},),
        ).to_dict(),
        HarnessWorkerResult(status="succeeded", output={"candidate": {"summary": "ok"}}).to_dict(),
        HarnessQualityVerdict(passed=True, score=0.9).to_dict(),
        event.to_dict(),
        trace.to_dict(),
        checkpoint.to_dict(),
    ]

    for payload in payloads:
        assert isinstance(payload, dict)
        assert payload


def test_trace_rejects_event_from_other_run() -> None:
    trace = HarnessTrace(run_id="run-1")
    event = HarnessEvent(event_type="run_created", run_id="run-2")

    try:
        trace.append(event)
    except Exception as exc:
        assert exc.__class__.__name__ == "HarnessValidationError"
    else:
        raise AssertionError("expected HarnessValidationError")


def test_trace_serializes_deterministic_history_only_when_explicitly_requested() -> None:
    event = HarnessEvent(
        event_type="decision_recorded",
        run_id="run-history",
        deterministic_history={
            "schema": "newsroom.harness-deterministic-history/v1",
            "handler_input": {"state_checksum": "sha256:before"},
        },
    )
    trace = HarnessTrace(run_id="run-history", events=(event,))

    public_payload = trace.to_dict()
    persistence_payload = trace.to_dict(include_deterministic_history=True)

    assert "deterministic_history" not in public_payload["events"][0]
    assert persistence_payload["events"][0]["deterministic_history"] == {
        "schema": "newsroom.harness-deterministic-history/v1",
        "handler_input": {"state_checksum": "sha256:before"},
    }
    restored = HarnessTrace.from_dict(persistence_payload)
    assert restored.to_dict(include_deterministic_history=True) == persistence_payload


def test_versioned_gate_contracts_are_public_and_quality_gate_stays_a_string() -> None:
    reference = GateReference.parse("candidate_schema@2")
    step = HarnessStepSpec(
        step_id="collect",
        worker_type="llm",
        quality_gate=str(reference),
    )

    payload = step.to_dict()

    assert payload["quality_gate"] == "candidate_schema@2"
    assert isinstance(payload["quality_gate"], str)
    assert set(payload) == {
        "step_id",
        "worker_type",
        "input_keys",
        "output_key",
        "retry_policy",
        "quality_gate",
        "metadata",
    }
    assert GateBinding.__module__ == "framework.harness.control_plane.gate_registry"
    assert GateRegistration.__module__ == "framework.harness.control_plane.gate_registry"
    assert DeterministicGateRegistry.__module__ == "framework.harness.control_plane.gate_registry"


@pytest.mark.parametrize("quality_gate", ("", 1, GateReference.parse("schema@1")))
def test_quality_gate_rejects_non_string_or_blank_serialization_values(
    quality_gate: object,
) -> None:
    with pytest.raises(HarnessValidationError, match="non-blank string"):
        HarnessStepSpec(
            step_id="collect",
            worker_type="llm",
            quality_gate=quality_gate,  # type: ignore[arg-type]
        )
