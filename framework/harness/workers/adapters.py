from __future__ import annotations

from typing import Any, Callable

from framework.harness.workers.result import HarnessWorkerResult


class CallableLLMWorkerAdapter:
    def __init__(self, generate: Callable[[dict[str, Any]], HarnessWorkerResult]) -> None:
        self._generate = generate

    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        return self._generate(request)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.generate(task)


class CallableSkillWorkerAdapter:
    def __init__(self, run_skill: Callable[[str, dict[str, Any], dict[str, Any]], HarnessWorkerResult]) -> None:
        self._run_skill = run_skill

    def run_skill(self, skill_name: str, inputs: dict[str, Any], context: dict[str, Any]) -> HarnessWorkerResult:
        return self._run_skill(skill_name, inputs, context)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.run_skill(
            str(task.get("skill_name", task.get("step_id", "skill"))),
            dict(task.get("inputs", {})),
            dict(task.get("context", task.get("metadata", {}))),
        )


class CallableSubAgentWorkerAdapter:
    def __init__(self, run_subagent: Callable[[str, dict[str, Any], dict[str, Any]], HarnessWorkerResult]) -> None:
        self._run_subagent = run_subagent

    def run_subagent(self, subagent_id: str, task: dict[str, Any], budget: dict[str, Any]) -> HarnessWorkerResult:
        return self._run_subagent(subagent_id, task, budget)

    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        return self.run_subagent(
            str(task.get("subagent_id", task.get("step_id", "subagent"))),
            dict(task),
            dict(task.get("budget", {})),
        )


__all__ = ["CallableLLMWorkerAdapter", "CallableSkillWorkerAdapter", "CallableSubAgentWorkerAdapter"]
