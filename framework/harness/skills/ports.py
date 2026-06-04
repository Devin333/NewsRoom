from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.workers.result import HarnessWorkerResult


@runtime_checkable
class SkillWorkerPort(Protocol):
    def run_skill(self, skill_name: str, inputs: dict[str, Any], context: dict[str, Any]) -> HarnessWorkerResult:
        ...


__all__ = ["SkillWorkerPort"]
