from __future__ import annotations

from pathlib import Path
from typing import Any

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.run_result import RunResult
from core.framework.specs import WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.step_runner import FunctionStepRegistry, FunctionStepRunner


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        function_registry: FunctionStepRegistry,
    ) -> None:
        self._artifact_manager = ArtifactManager(artifact_root)
        self._function_step_runner = FunctionStepRunner(function_registry)

    def run(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=self._function_step_runner,
            artifact_manager=self._artifact_manager,
        )
        result = executor.execute(workflow, request, profile=profile, run_id=run_id)
        return RunResult.from_workflow_result(result)
