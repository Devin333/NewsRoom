from __future__ import annotations

from framework.scoring import ScoringStepTrace, ScoringTrace
from framework.shared.time import utc_now
from framework.shared.graph_identity import GraphExecutionIdentity


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


def test_scoring_trace_binds_graph_execution_identity() -> None:
    identity = GraphExecutionIdentity(
        run_id="run-1",
        graph_id="graph",
        graph_version="v1",
        graph_ref="graph@v1",
        graph_checksum="sha256:" + "b" * 64,
        node_id="node",
        node_instance_id="node-instance",
        activity_id="activity",
        attempt=1,
    )
    trace = ScoringTrace.create(recipe_id="recipe", execution_identity=identity)
    trace = trace.add_step(
        ScoringStepTrace(
            step_id="scorer",
            step_type="scorer",
            status="started",
            started_at=utc_now(),
            execution_identity=identity,
        ).finish()
    )

    assert ScoringTrace.from_dict(trace.to_dict()).execution_identity == identity
