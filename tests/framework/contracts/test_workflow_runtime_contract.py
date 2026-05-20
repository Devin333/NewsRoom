from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from framework.workflow.runners.base import StepRunnerCapability, StepRunnerSideEffectLevel
from framework.workflow.runners.registry import StepRunnerRegistry
from framework.workflow.runtime.artifacts import ArtifactManager
from framework.workflow.runtime.executor import WorkflowExecutor
from framework.workflow.runtime.result import StepOutcome


class _FunctionRunner:
    capability = StepRunnerCapability(
        step_type=StepType.FUNCTION,
        runner_id="contract.runner",
        version="1.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=True,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
    )

    def __init__(self, outputs: dict[str, dict[str, Any]]) -> None:
        self._outputs = outputs

    def can_resolve(self, step: StepSpec) -> bool:
        return step.step_type == StepType.FUNCTION

    def validate_step(self, step: StepSpec) -> list[Any]:
        return []

    def run(self, step: StepSpec, buffer: Any) -> StepOutcome:
        return StepOutcome(status=StepStatus.SUCCEEDED, outputs=self._outputs.get(step.step_id, {}))


def _executor(tmp_path: Path, outputs: dict[str, dict[str, Any]], **kwargs: Any) -> WorkflowExecutor:
    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, _FunctionRunner(outputs))
    return WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
        **kwargs,
    )


def test_workflow_runtime_contract_two_step_run(tmp_path: Path) -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-contract",
        name="Workflow Contract",
        version="1.0",
        steps=[
            StepSpec(step_id="s1", write_keys=["a"]),
            StepSpec(step_id="s2", read_keys=["a"], write_keys=["b"]),
        ],
        edges=[{"source_step_id": "s1", "target_step_id": "s2", "condition": "on_success"}],
        terminal_step_ids=["s2"],
    )

    result = _executor(tmp_path, {"s1": {"a": 1}, "s2": {"b": 2}}).execute(
        workflow,
        {},
        profile="contract",
        run_id="run-workflow-contract",
    )
    event_types = [
        json.loads(line)["event_type"]
        for line in Path(result.events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.trace_id
    assert result.manifest_ref == result.manifest_path
    assert result.path == ["s1", "s2"]
    assert result.step_results["s1"].trace_id == result.trace_id
    assert result.step_results["s1"].gate_result["decision"] == "pass"
    assert result.manifest["step_summaries"][0]["step_id"] == "s1"
    assert result.manifest["trace_ref"] == "events.jsonl"
    assert event_types[0] == "workflow_started"
    assert "step_succeeded" in event_types
    assert event_types[-1] == "workflow_succeeded"


def test_runtime_verification_strict_fails_contract_violation(tmp_path: Path) -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-contract-strict",
        name="Workflow Contract",
        version="1.0",
        steps=[
            StepSpec(
                step_id="s1",
                write_keys=["ok"],
                runtime_quality={
                    "evaluation": {
                        "enabled": True,
                        "required_output_keys": ["ok"],
                        "fail_on_missing_required_output": False,
                    },
                    "gate": {"mode": "warn_only", "dimensions": ["correctness"]},
                },
            )
        ],
        terminal_step_ids=["s1"],
    )

    result = _executor(
        tmp_path,
        {"s1": {}},
        runtime_verification_mode="strict",
    ).execute(workflow, {}, profile="contract", run_id="run-verification-strict")

    assert result.status == WorkflowStatus.FAILED
    assert result.error.error_type == "RuntimeVerificationFailed"
    assert result.manifest["runtime_verification"]["passed"] is False
    assert result.manifest["runtime_verification"]["issues"][0]["code"] == "step.required_outputs_missing"


def test_runtime_verification_warn_records_report_without_changing_status(tmp_path: Path) -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-contract-warn",
        name="Workflow Contract",
        version="1.0",
        steps=[
            StepSpec(
                step_id="s1",
                write_keys=["ok"],
                runtime_quality={
                    "evaluation": {
                        "enabled": True,
                        "required_output_keys": ["ok"],
                        "fail_on_missing_required_output": False,
                    },
                    "gate": {"mode": "warn_only", "dimensions": ["correctness"]},
                },
            )
        ],
        terminal_step_ids=["s1"],
    )

    result = _executor(
        tmp_path,
        {"s1": {}},
        runtime_verification_mode="warn",
    ).execute(workflow, {}, profile="contract", run_id="run-verification-warn")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.manifest["runtime_verification"]["passed"] is False
    assert any("missing required output keys" in warning for warning in result.manifest["warnings"])
