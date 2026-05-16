from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
    WorkflowResult,
)


def make_step(
    step_id: str,
    implementation: str | None = None,
    *,
    step_type: StepType | str = StepType.FUNCTION,
    read_keys: list[str] | None = None,
    write_keys: list[str] | None = None,
    required_output_keys: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    **kwargs: Any,
) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        implementation=implementation or f"test.{step_id}",
        step_type=step_type,
        read_keys=list(read_keys or []),
        write_keys=list(write_keys or []),
        required_output_keys=list(required_output_keys or []),
        metadata=dict(metadata or {}),
        **kwargs,
    )


def make_edge(
    source_step_id: str,
    target_step_id: str,
    *,
    edge_id: str | None = None,
    condition: EdgeCondition | str = EdgeCondition.ON_SUCCESS,
    condition_expr: str | None = None,
    priority: int = 0,
    metadata: dict[str, Any] | None = None,
) -> EdgeSpec:
    return EdgeSpec(
        edge_id=edge_id or f"{source_step_id}-to-{target_step_id}",
        source_step_id=source_step_id,
        target_step_id=target_step_id,
        condition=condition,
        condition_expr=condition_expr,
        priority=priority,
        metadata=dict(metadata or {}),
    )


def make_linear_workflow(
    step_ids: list[str] | tuple[str, ...] = ("start", "finish"),
    *,
    workflow_id: str = "contract-linear",
    version: str = "1.0",
    request_read_keys: list[str] | None = None,
) -> WorkflowSpec:
    steps: list[StepSpec] = []
    edges: list[EdgeSpec] = []
    previous_output_key: str | None = None
    for index, step_id in enumerate(step_ids):
        read_keys = list(request_read_keys or ["request"]) if index == 0 else [str(previous_output_key)]
        output_key = _step_output_key(step_id)
        steps.append(
            make_step(
                step_id,
                read_keys=read_keys,
                write_keys=[output_key],
                required_output_keys=[output_key],
            )
        )
        if index > 0:
            edges.append(make_edge(str(step_ids[index - 1]), step_id))
        previous_output_key = output_key

    return WorkflowSpec(
        workflow_id=workflow_id,
        name="Contract Linear",
        version=version,
        start_step_id=str(step_ids[0]),
        terminal_step_ids=[str(step_ids[-1])],
        steps=steps,
        edges=edges,
    )


def make_branching_workflow(
    *,
    workflow_id: str = "contract-branching",
) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=workflow_id,
        name="Contract Branching",
        version="1.0",
        start_step_id="start",
        terminal_step_ids=["left", "right"],
        steps=[
            make_step("start", read_keys=["request"], write_keys=["root"], required_output_keys=["root"]),
            make_step("left", read_keys=["root"], write_keys=["left"], required_output_keys=["left"]),
            make_step("right", read_keys=["root"], write_keys=["right"], required_output_keys=["right"]),
        ],
        edges=[
            make_edge("start", "left", condition=EdgeCondition.ALWAYS, priority=0),
            make_edge("start", "right", condition=EdgeCondition.ALWAYS, priority=1),
        ],
    )


def make_human_review_workflow(*, workflow_id: str = "contract-human-review") -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=workflow_id,
        name="Contract Human Review",
        version="1.0",
        start_step_id="review",
        terminal_step_ids=["review"],
        steps=[
            make_step(
                "review",
                "human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request"],
                write_keys=["human_review_request"],
                required_output_keys=["human_review_request"],
            )
        ],
    )


def make_function_registry(
    implementations: Mapping[str, Callable[[Any], dict[str, Any] | None]] | None = None,
) -> FunctionStepRegistry:
    registry = FunctionStepRegistry()
    for implementation, function in (implementations or {}).items():
        registry.register(implementation, function)
    return registry


def make_registry_for_linear_workflow(workflow: WorkflowSpec) -> FunctionStepRegistry:
    registry = FunctionStepRegistry()
    for step in workflow.steps:
        output_keys = list(step.write_keys)

        def _function(buffer: Any, *, actual_step: StepSpec = step, keys: list[str] = output_keys) -> dict[str, Any]:
            seed = _read_first_available(buffer, actual_step.read_keys)
            return {key: _output_value(actual_step.step_id, seed) for key in keys}

        registry.register(step.implementation, _function)
    return registry


def run_workflow(
    tmp_path: Path,
    workflow: WorkflowSpec,
    registry: FunctionStepRegistry | StepRunnerRegistry | None = None,
    request: dict[str, Any] | None = None,
    *,
    profile: str = "test",
    run_id: str = "contract-run",
    checkpoint_store: Any | None = None,
    global_budget_tracker: Any | None = None,
) -> WorkflowResult:
    if isinstance(registry, StepRunnerRegistry):
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=registry,
            artifact_manager=ArtifactManager(tmp_path),
            checkpoint_store=checkpoint_store,
            global_budget_tracker=global_budget_tracker,
        )
    else:
        function_registry = registry or make_registry_for_linear_workflow(workflow)
        executor = WorkflowExecutor(
            function_step_runner=FunctionStepRunner(function_registry),
            artifact_manager=ArtifactManager(tmp_path),
            checkpoint_store=checkpoint_store,
            global_budget_tracker=global_budget_tracker,
        )
    return executor.execute(
        workflow,
        request or {"topic": "contract"},
        profile=profile,
        run_id=run_id,
    )


def run_dir(artifact_root: Path, run_id: str) -> Path:
    return artifact_root / run_id


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest(run_directory: Path) -> dict[str, Any]:
    return read_json(run_directory / "manifest.json")


def read_events(run_directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (run_directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_json_artifact(run_directory: Path, name: str) -> Any:
    return read_json(run_directory / name)


def _step_output_key(step_id: str) -> str:
    return f"{step_id}_output"


def _read_first_available(buffer: Any, keys: list[str]) -> Any:
    for key in keys:
        try:
            return buffer.read(key)
        except Exception:
            continue
    return None


def _output_value(step_id: str, seed: Any) -> dict[str, Any]:
    return {"step_id": step_id, "seed": seed}
