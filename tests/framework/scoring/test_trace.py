from __future__ import annotations

from framework.scoring import ScoringStepTrace, ScoringTrace
from framework.shared.time import utc_now


def test_scoring_step_trace_finish_sets_duration() -> None:
    step = ScoringStepTrace(step_id="scorer", step_type="scorer", status="started", started_at=utc_now())

    finished = step.finish(output_summary={"score": 0.8})

    assert finished.status == "succeeded"
    assert finished.ended_at is not None
    assert finished.duration_ms is not None
    assert finished.to_dict()["output_summary"]["score"] == 0.8


def test_scoring_trace_round_trips() -> None:
    trace = ScoringTrace.create(recipe_id="recipe", target_id="target", target_type="board_card")
    trace = trace.add_step(
        ScoringStepTrace(step_id="scorer", step_type="scorer", status="started", started_at=utc_now()).finish()
    )

    restored = ScoringTrace.from_dict(trace.to_dict())

    assert restored.trace_id == trace.trace_id
    assert restored.steps[0].step_id == "scorer"
