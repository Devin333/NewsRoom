from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.trace import HarnessTrace
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.runtime.checkpoint import HarnessCheckpoint
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillPromotionDecision,
)
from framework.harness.workers.result import HarnessWorkerResult


@runtime_checkable
class HarnessLLMPort(Protocol):
    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessToolPort(Protocol):
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessMemoryPort(Protocol):
    def recall(self, query: dict[str, Any]) -> HarnessWorkerResult:
        ...

    def write(self, intent: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessSkillPort(Protocol):
    def run_skill(self, skill_id: str, inputs: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessArtifactPort(Protocol):
    def publish(self, payload: dict[str, Any]) -> str:
        ...


@runtime_checkable
class HarnessEventPort(Protocol):
    def record(self, event: HarnessEvent) -> None:
        ...


@runtime_checkable
class HarnessWorkerPort(Protocol):
    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessGovernancePort(Protocol):
    def evaluate(self, context: dict[str, Any]) -> HarnessQualityVerdict:
        ...


@runtime_checkable
class HarnessSubagentPort(Protocol):
    def run_subagent(self, task: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessContextPort(Protocol):
    def assemble(self, context_request: dict[str, Any]) -> dict[str, Any]:
        ...


@runtime_checkable
class HarnessRAGPort(Protocol):
    def build_context_pack(self, request: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessCheckpointPort(Protocol):
    def save_checkpoint(self, checkpoint: HarnessCheckpoint) -> None:
        ...


@runtime_checkable
class HarnessTracePort(Protocol):
    def write_trace(self, trace: HarnessTrace) -> None:
        ...


@runtime_checkable
class HarnessSkillEvolutionPort(Protocol):
    def validate_candidate(self, candidate: SkillCandidate) -> HarnessWorkerResult:
        ...

    def evaluate_candidate(self, candidate: SkillCandidate) -> SkillEvaluationResult:
        ...

    def decide_promotion(self, evaluation: SkillEvaluationResult) -> SkillPromotionDecision:
        ...


__all__ = [
    "HarnessArtifactPort",
    "HarnessCheckpointPort",
    "HarnessContextPort",
    "HarnessEventPort",
    "HarnessGovernancePort",
    "HarnessLLMPort",
    "HarnessMemoryPort",
    "HarnessRAGPort",
    "HarnessSkillEvolutionPort",
    "HarnessSkillPort",
    "HarnessSubagentPort",
    "HarnessToolPort",
    "HarnessTracePort",
    "HarnessWorkerPort",
]
