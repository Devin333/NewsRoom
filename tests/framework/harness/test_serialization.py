from __future__ import annotations

from framework.harness import (
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
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)


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
