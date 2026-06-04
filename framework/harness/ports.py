from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.artifacts.ports import ArtifactRef, ArtifactWriteRequest
from framework.harness.context.models import ContextEnvelope
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.trace import HarnessTrace
from framework.harness.mcp.policy import MCPToolDefinition, MCPToolRequest
from framework.harness.memory.ports import MemoryWriteCandidate
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.rag.models import RAGContextPack, RAGSessionRequest
from framework.harness.retrieval.evidence_pack import EvidencePackCollection
from framework.harness.retrieval.request import RetrievalRequest
from framework.harness.runtime.checkpoint import HarnessCheckpoint
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperience,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
)
from framework.harness.workers.result import HarnessWorkerResult


@runtime_checkable
class HarnessLLMPort(Protocol):
    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessToolPort(Protocol):
    def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        ...

    def call_tool(self, request: MCPToolRequest) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessMemoryPort(Protocol):
    def recall(self, query: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        ...

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        ...

    def commit_write(self, approved_write: MemoryWriteCandidate) -> MemoryWriteCandidate:
        ...


@runtime_checkable
class HarnessSkillPort(Protocol):
    def run_skill(self, skill_id: str, inputs: dict[str, Any], context: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessArtifactPort(Protocol):
    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        ...

    def read_artifact(self, ref: str) -> dict[str, Any]:
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
    def run_subagent(self, subagent_id: str, task: dict[str, Any], budget: dict[str, Any]) -> HarnessWorkerResult:
        ...


@runtime_checkable
class HarnessContextPort(Protocol):
    def assemble(self, context_request: dict[str, Any]) -> ContextEnvelope:
        ...


@runtime_checkable
class HarnessRAGPort(Protocol):
    def build_context_pack(self, request: RAGSessionRequest) -> RAGContextPack:
        ...


@runtime_checkable
class HarnessRetrievalPort(Protocol):
    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection:
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
    def collect_experience(self, request: dict[str, Any]) -> SkillExperience:
        ...

    def propose_candidate(self, request: dict[str, Any]) -> SkillCandidate:
        ...

    def evaluate_candidate(self, candidate: SkillCandidate) -> SkillEvaluationResult:
        ...

    def decide_promotion(self, evaluation: SkillEvaluationResult) -> SkillPromotionDecision:
        ...

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease:
        ...

    def rollback_release(self, release: SkillRelease) -> SkillRollbackPlan:
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
    "HarnessRetrievalPort",
    "HarnessSkillEvolutionPort",
    "HarnessSkillPort",
    "HarnessSubagentPort",
    "HarnessToolPort",
    "HarnessTracePort",
    "HarnessWorkerPort",
]
