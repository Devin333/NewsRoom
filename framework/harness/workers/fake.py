from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workers.result import HarnessWorkerResult


class FakeLLMWorker:
    def __init__(self, responses: Iterable[HarnessWorkerResult] | None = None) -> None:
        self._responses = list(responses or [HarnessWorkerResult(status="succeeded", output={"candidate": {}})])
        self.requests: list[dict[str, Any]] = []

    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        self.requests.append(dict(request))
        return _next_result(self._responses)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.generate(task)


class FakeSkillWorker:
    def __init__(
        self,
        *,
        skill_name: str = "research.skill",
        skill_version: str = "0.1.0",
        package_hash: str = "sha256:fake",
        responses: Iterable[HarnessWorkerResult] | None = None,
    ) -> None:
        self.skill_name = skill_name
        self.skill_version = skill_version
        self.package_hash = package_hash
        self._responses = list(responses or [HarnessWorkerResult(status="succeeded", output={"result": {}})])
        self.calls: list[dict[str, Any]] = []

    def run_skill(self, skill_name: str, inputs: dict[str, Any], context: dict[str, Any]) -> HarnessWorkerResult:
        call = {"skill_name": skill_name, "inputs": dict(inputs), "context": dict(context)}
        self.calls.append(call)
        result = _next_result(self._responses)
        diagnostics = {
            **result.diagnostics,
            "skill_name": skill_name,
            "skill_version": self.skill_version,
            "package_hash": self.package_hash,
        }
        return HarnessWorkerResult(
            status=result.status,
            output=result.output,
            artifacts=result.artifacts,
            diagnostics=diagnostics,
            metrics=result.metrics,
            error=result.error,
        )

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.run_skill(
            str(task.get("skill_name") or self.skill_name),
            dict(task.get("inputs", {})),
            dict(task.get("context", task.get("metadata", {}))),
        )


class FakeSubAgentWorker:
    def __init__(self, responses: Iterable[HarnessWorkerResult] | None = None) -> None:
        self._responses = list(responses or [HarnessWorkerResult(status="succeeded", output={"handoff": {}})])
        self.calls: list[dict[str, Any]] = []

    def run_subagent(self, subagent_id: str, task: dict[str, Any], budget: dict[str, Any]) -> HarnessWorkerResult:
        self.calls.append({"subagent_id": subagent_id, "task": dict(task), "budget": dict(budget)})
        return _next_result(self._responses)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.run_subagent(
            str(task.get("subagent_id", task.get("step_id", "subagent"))),
            dict(task),
            dict(task.get("budget", {})),
        )


def _next_result(responses: list[HarnessWorkerResult]) -> HarnessWorkerResult:
    if not responses:
        raise HarnessValidationError("fake worker has no remaining responses")
    if len(responses) == 1:
        return responses[0]
    return responses.pop(0)


__all__ = ["FakeLLMWorker", "FakeSkillWorker", "FakeSubAgentWorker"]
