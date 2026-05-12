from __future__ import annotations

import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.tools import build_builtin_tool_registry
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepExecutionError,
    StepRunnerRegistry,
    ToolBatchStepRunner,
    WorkflowExecutor,
)


def test_tool_batch_step_runner_executes_real_builtin_tools(tmp_path) -> None:
    tool_registry = build_builtin_tool_registry(include_network_tools=False)
    step_runner_registry = StepRunnerRegistry.with_function_runner(
        FunctionStepRunner(FunctionStepRegistry())
    )
    step_runner_registry.register(StepType.TOOL_BATCH, ToolBatchStepRunner(tool_registry))
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=step_runner_registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        WorkflowSpec(
            workflow_id="tool-batch",
            name="Tool Batch",
            version="1.0",
            start_step_id="tools",
            steps=[
                StepSpec(
                    step_id="tools",
                    implementation="tools.batch",
                    step_type=StepType.TOOL_BATCH,
                    write_keys=["tool_observations", "tool_results"],
                    required_output_keys=["tool_observations", "tool_results"],
                    metadata={
                        "tool_policy": {
                            "allowed_tools": [
                                "report.validate",
                                "quality.duplicate_check",
                            ],
                            "max_tool_calls_per_iteration": 2,
                        },
                        "tool_calls": [
                            {
                                "tool_name": "report.validate",
                                "call_id": "validate-report",
                                "arguments": {
                                    "report": {
                                        "title": "Daily Brief",
                                        "sections": [{"content": "Supported update"}],
                                        "source_urls": ["https://example.com/source"],
                                    }
                                },
                            },
                            {
                                "tool_name": "quality.duplicate_check",
                                "call_id": "dedup-items",
                                "arguments": {
                                    "items": [
                                        {
                                            "item_id": "a",
                                            "title": "Same",
                                            "url": "https://example.com/a?utm_source=x",
                                        },
                                        {
                                            "item_id": "b",
                                            "title": "Same",
                                            "url": "https://example.com/a",
                                        },
                                    ]
                                },
                            },
                        ],
                    },
                )
            ],
        ),
        {"topic": "ai"},
        profile="test",
        run_id="run-tool-batch",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.step_results["tools"].status == StepStatus.SUCCEEDED
    assert [item["status"] for item in result.output["tool_observations"]] == [
        "succeeded",
        "succeeded",
    ]
    assert result.output["tool_results"][0]["output"]["valid"] is True
    assert result.output["tool_results"][1]["output"]["duplicate_group_count"] == 1
    manifest = json.loads((tmp_path / "run-tool-batch" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["steps"]["tools"]["outputs"]["tool_results"][0]["status"] == "succeeded"


def test_tool_batch_step_runner_fails_when_tool_is_blocked(tmp_path) -> None:
    tool_registry = build_builtin_tool_registry()
    step_runner_registry = StepRunnerRegistry.with_function_runner(
        FunctionStepRunner(FunctionStepRegistry())
    )
    step_runner_registry.register(StepType.TOOL_BATCH, ToolBatchStepRunner(tool_registry))
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=step_runner_registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        WorkflowSpec(
            workflow_id="tool-batch-blocked",
            name="Tool Batch Blocked",
            version="1.0",
            start_step_id="tools",
            steps=[
                StepSpec(
                    step_id="tools",
                    implementation="tools.batch",
                    step_type=StepType.TOOL_BATCH,
                    write_keys=["tool_observations", "tool_results"],
                    metadata={
                        "tool_policy": {"allowed_tools": ["report.validate"]},
                        "tool_calls": [
                            {
                                "tool_name": "web.search",
                                "call_id": "blocked-search",
                                "arguments": {"query": "AI policy"},
                            }
                        ],
                    },
                )
            ],
        ),
        {"topic": "ai"},
        profile="test",
        run_id="run-tool-batch-blocked",
    )

    assert result.status == WorkflowStatus.FAILED
    assert result.step_results["tools"].status == StepStatus.FAILED
    assert result.error is not None
    assert result.error.error_type == "ToolBatchStepFailed"
    assert result.error.details["failed_tool_calls"][0]["status"] == "blocked"
    assert result.output["tool_observations"][0]["status"] == "blocked"


def test_tool_batch_step_missing_runner_fails_before_run_creation(tmp_path) -> None:
    spec = WorkflowSpec(
        workflow_id="tool-batch-missing-runner",
        name="Missing Tool Batch Runner",
        version="1.0",
        start_step_id="tools",
        steps=[
            StepSpec(
                step_id="tools",
                implementation="tools.batch",
                step_type=StepType.TOOL_BATCH,
                write_keys=["tool_observations"],
                metadata={"tool_calls": []},
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    with pytest.raises(StepExecutionError, match="not registered: tool_batch"):
        executor.execute(spec, {"topic": "ai"}, profile="test", run_id="run-missing-tool-batch")

    assert not (tmp_path / "run-missing-tool-batch").exists()
