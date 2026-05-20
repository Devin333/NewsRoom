from __future__ import annotations

import json

from framework.specs import StepStatus
from framework.workflow.runtime.artifacts import ArtifactRef
from framework.workflow.runtime.result import StepOutcome


def test_step_outcome_accepts_old_payload_and_outputs_standard_fields() -> None:
    outcome = StepOutcome.from_dict(
        {
            "status": "succeeded",
            "outputs": {"ok": True},
            "metrics": {"attempt": 1},
        }
    )

    payload = outcome.to_dict()

    assert outcome.status == StepStatus.SUCCEEDED
    assert payload["outputs"] == {"ok": True}
    assert "trace_id" in payload
    assert "duration_ms" in payload
    assert "error_envelope" in payload


def test_step_outcome_round_trip_keeps_trace_timing_refs_and_warnings() -> None:
    artifact_ref = ArtifactRef(
        artifact_id="artifact-1",
        run_id="run-1",
        step_id="s1",
        artifact_type="json",
        path="steps/s1/output.json",
        content_type="application/json",
    )
    outcome = StepOutcome(
        status=StepStatus.SUCCEEDED,
        outputs={"ok": True},
        step_id="s1",
        trace_id="trace-1",
        span_id="span-1",
        trace_events=[{"event_id": "evt-1"}],
        artifacts=[artifact_ref],
        evidence_refs=[{"evidence_id": "ev-1"}],
        gate_result={"allowed": True},
        checkpoint_ref="cp-1",
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:00:01Z",
        warnings=["soft warning"],
        metadata={"runner": "test"},
    )

    payload = json.loads(json.dumps(outcome.to_dict()))
    restored = StepOutcome.from_dict(payload)

    assert restored.step_id == "s1"
    assert restored.trace_id == "trace-1"
    assert restored.span_id == "span-1"
    assert restored.duration_ms == 1000.0
    assert restored.artifact_refs[0]["artifact_id"] == "artifact-1"
    assert restored.evidence_refs == [{"evidence_id": "ev-1"}]
    assert restored.gate_result == {"allowed": True}
    assert restored.checkpoint_ref == "cp-1"
    assert restored.warnings == ["soft warning"]


def test_step_outcome_failure_factory_populates_legacy_and_standard_error() -> None:
    outcome = StepOutcome.failure("s2", RuntimeError("boom"))

    assert outcome.status == StepStatus.FAILED
    assert outcome.step_id == "s2"
    assert outcome.error is not None
    assert outcome.error.details["step_id"] == "s2"
    assert outcome.error_envelope_dict is not None
    assert outcome.error_envelope_dict["step_id"] == "s2"
    assert outcome.error_envelope_dict["domain"] == "workflow.step"
