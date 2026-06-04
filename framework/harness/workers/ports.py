from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.workers.result import HarnessWorkerResult


@runtime_checkable
class LLMWorkerPort(Protocol):
    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class SkillWorkerPort(Protocol):
    def run_skill(self, skill_name: str, inputs: dict[str, Any], context: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class SubAgentWorkerPort(Protocol):
    def run_subagent(self, subagent_id: str, task: dict[str, Any], budget: dict[str, Any]) -> HarnessWorkerResult:
        ...


__all__ = ["LLMWorkerPort", "SkillWorkerPort", "SubAgentWorkerPort"]
