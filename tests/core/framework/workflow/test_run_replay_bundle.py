from __future__ import annotations

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    WorkflowExecutor,
    WorkflowTimelineBuilder,
    build_workflow_replay_bundle,
    build_workflow_replay_content_bundle,
)


def test_replay_bundle_contains_core_debug_artifacts(tmp_path) -> None:
    executor = _routing_executor(tmp_path)
    executor.execute(_routing_spec(), {"topic": "ai"}, profile="test", run_id="replay-core")

    bundle = build_workflow_replay_bundle(tmp_path / "replay-core", strict=True)

    assert bundle.manifest["run_id"] == "replay-core"
    assert bundle.request == {"topic": "ai"}
    assert bundle.step_results["plan"]["status"] == "succeeded"
    assert bundle.events
    assert bundle.step_timeline[0].step_id == "plan"


def test_replay_content_bundle_expands_small_artifacts_and_redacts(tmp_path) -> None:
    executor = _routing_executor(tmp_path)
    executor.execute(
        _routing_spec(),
        {"topic": "ai", "api_key": "secret"},
        profile="test",
        run_id="replay-content",
    )

    bundle = build_workflow_replay_content_bundle(
        tmp_path / "replay-content",
        redact=True,
        max_artifact_bytes=10,
    )

    assert bundle.artifact_by_key("request").truncated is True
    assert "secret" not in str(bundle.to_dict())


def test_workflow_timeline_builder_records_attempts_and_retries() -> None:
    items = WorkflowTimelineBuilder().build(
        [
            {"event_type": "step_started", "occurred_at": "2026-05-16T00:00:00Z", "payload": {"step_id": "a"}},
            {"event_type": "step_retry_scheduled", "occurred_at": "2026-05-16T00:00:01Z", "payload": {"step_id": "a"}},
            {"event_type": "step_started", "occurred_at": "2026-05-16T00:00:02Z", "payload": {"step_id": "a"}},
            {"event_type": "step_failed", "occurred_at": "2026-05-16T00:00:03Z", "payload": {"step_id": "a"}},
        ]
    )

    assert items[0].step_id == "a"
    assert items[0].attempts == 2
    assert items[0].retry_count == 1
    assert items[0].status == "failed"


def test_replay_bundle_exposes_routing_evaluations_and_selected_edge(tmp_path) -> None:
    executor = _routing_executor(tmp_path)
    executor.execute(_routing_spec(), {"topic": "ai"}, profile="test", run_id="replay-routing")

    bundle = build_workflow_replay_bundle(tmp_path / "replay-routing", strict=True)
    routing = bundle.routing_diagnostics

    assert routing["selected_edge_id"] == "plan-to-write"
    assert any(
        item["edge_id"] == "plan-to-write" and item["matched"] is True
        for item in routing["evaluations"]
    )


def test_conditional_edge_false_records_rejected_evaluation(tmp_path) -> None:
    executor = _routing_executor(tmp_path)
    executor.execute(_routing_spec(), {"topic": "ai"}, profile="test", run_id="replay-rejected")

    bundle = build_workflow_replay_bundle(tmp_path / "replay-rejected", strict=True)

    assert "plan-to-never" in bundle.routing_diagnostics["rejected_edge_ids"]
    assert any(
        item["edge_id"] == "plan-to-never" and item["matched"] is False
        for item in bundle.routing_diagnostics["evaluations"]
    )


def _routing_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="replay-sample",
        name="Replay Sample",
        version="1.0",
        start_step_id="plan",
        steps=[
            StepSpec("plan", "sample.plan", read_keys=["request"], write_keys=["plan"]),
            StepSpec("write", "sample.write", read_keys=["plan"], write_keys=["report"]),
            StepSpec("never", "sample.write", write_keys=["never"]),
        ],
        edges=[
            EdgeSpec(
                "plan-to-never",
                "plan",
                "never",
                condition="conditional",
                condition_expr="false",
                priority=0,
            ),
            EdgeSpec("plan-to-write", "plan", "write", priority=1),
        ],
    )


def _routing_executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    functions.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    return WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
