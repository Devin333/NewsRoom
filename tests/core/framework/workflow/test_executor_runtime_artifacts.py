from __future__ import annotations

import json
from pathlib import Path

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import FunctionStepRegistry, FunctionStepRunner, WorkflowExecutor


def test_executor_runtime_artifacts_for_successful_function_workflow(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("runtime.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    registry.register("runtime.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _runtime_spec(),
        {"topic": "ai"},
        profile="test",
        run_id="runtime-success",
    )

    run_dir = tmp_path / "runtime-success"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.status == WorkflowStatus.SUCCEEDED
    assert (run_dir / "request.json").exists()
    assert (run_dir / "workflow_spec.json").exists()
    assert (run_dir / "data_buffer.initial.json").exists()
    assert (run_dir / "output.json").exists()
    assert (run_dir / "data_buffer.final.json").exists()
    assert (run_dir / "data_buffer.diff.json").exists()
    assert (run_dir / "step_results.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert manifest["artifacts"]["output"] == "output.json"


def test_generic_workflow_does_not_need_news_domain_publisher(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("runtime.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    registry.register("runtime.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _runtime_spec(),
        {"topic": "ai"},
        profile="test",
        run_id="runtime-generic",
    )

    run_dir = tmp_path / "runtime-generic"
    assert result.status == WorkflowStatus.SUCCEEDED
    assert (run_dir / "output.json").exists()
    assert not (run_dir / "evidence_bundle.json").exists()
    assert not (run_dir / "report.md").exists()


def test_workflow_executor_has_no_daily_domain_artifact_keys() -> None:
    text = Path("core/framework/workflow/executor.py").read_text(encoding="utf-8")
    forbidden = [
        "evidence_bundle",
        "citation_check_result",
        "report_markdown",
        "blocked_report",
        "quality_result",
        "editor_review",
        "support_matrix",
    ]

    for key in forbidden:
        assert key not in text


def _runtime_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="runtime-artifacts",
        name="Runtime Artifacts",
        version="1.0",
        start_step_id="plan",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="runtime.plan",
                read_keys=["request"],
                write_keys=["plan"],
                required_output_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="runtime.write",
                read_keys=["plan"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[EdgeSpec(edge_id="plan-to-write", source_step_id="plan", target_step_id="write")],
    )
