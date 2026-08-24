from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from framework.harness.artifacts.ports import ArtifactRef, ArtifactWriteRequest
from framework.harness.context.models import ContextEnvelope
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.trace import HarnessTrace
from framework.harness.mcp.policy import MCPToolDefinition, MCPToolRequest
from framework.harness.memory.ports import MemoryWriteCandidate
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.rag.models import RAGContextPack, RAGSessionSpec
from framework.harness.retrieval.evidence_pack import EvidencePackCollection
from framework.harness.retrieval.request import RetrievalRequest
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperience,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
)
from framework.harness.workers.result import HarnessWorkerResult

if TYPE_CHECKING:
    from datetime import datetime

    from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
    from framework.harness.control_plane.graph_state import HarnessGraphState
    from framework.harness.graph.model import NormalizedHarnessGraph
    from framework.events.graph_phase import GraphPhaseTransitionRecord


@runtime_checkable
class HarnessLLMPort(Protocol):
    def generate(self, request: dict[str, Any]) -> HarnessWorkerResult: ...


@runtime_checkable
class HarnessToolPort(Protocol):
    def list_tools(self) -> tuple[MCPToolDefinition, ...]: ...

    def call_tool(self, request: MCPToolRequest) -> HarnessWorkerResult: ...


@runtime_checkable
class HarnessMemoryPort(Protocol):
    def recall(self, query: dict[str, Any]) -> tuple[dict[str, Any], ...]: ...

    def propose_write(
        self, candidate: MemoryWriteCandidate
    ) -> MemoryWriteCandidate: ...


@runtime_checkable
class HarnessSkillPort(Protocol):
    def run_skill(
        self, skill_id: str, inputs: dict[str, Any], context: dict[str, Any]
    ) -> HarnessWorkerResult: ...


@runtime_checkable
class HarnessArtifactPort(Protocol):
    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef: ...

    def read_artifact(self, ref: str) -> dict[str, Any]: ...


@runtime_checkable
class HarnessEventPort(Protocol):
    def record(self, event: HarnessEvent) -> HarnessEvent:
        """Commit an event and return its authoritative post-commit projection."""
        ...


@runtime_checkable
class HarnessTransitionPort(HarnessEventPort, Protocol):
    def record_graph_phase_transition(
        self,
        record: GraphPhaseTransitionRecord,
        *,
        expected_last_sequence: int,
    ) -> HarnessEvent:
        """Persist one exact Graph phase transition through the durable writer."""
        ...

    def accept_graph_activity(
        self,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        inputs: dict[str, Any],
        *,
        accepted_at: datetime,
        started_at: datetime,
    ) -> HarnessWorkerResult | None:
        """Persist one checksum-bound Graph activity before live work."""
        ...

    def record_graph_activity_result(
        self,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        result: HarnessWorkerResult,
        *,
        completed_at: datetime,
        graph_context: Any,
    ) -> HarnessEvent:
        """Persist one terminal worker result under the Graph activity identity."""
        ...

    def read_history(self, run_id: str) -> tuple[HarnessEvent, ...]: ...

    def require_activity_storage(self) -> None: ...

    def resolve_graph_replay_activity(
        self,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        inputs: dict[str, Any] | None = None,
    ) -> HarnessWorkerResult:
        """Read one graph activity result without accepting or dispatching work.

        Runtime hydration may omit inputs and trust the immutable activity
        descriptor. Offline verification supplies inputs to recheck the causal
        input checksum.
        """
        ...

@runtime_checkable
class HarnessGraphResultCommitterPort(Protocol):
    """Commit one recorded worker result as a verified Graph result lineage."""

    def commit_result(
        self,
        *,
        activity: HarnessGraphActivity,
        graph: NormalizedHarnessGraph,
        run_spec_checksum: str,
        worker_result: HarnessWorkerResult,
        occurred_at: datetime,
    ) -> HarnessGraphState:
        ...


@runtime_checkable
class HarnessWorkerPort(Protocol):
    def execute(self, task: dict[str, Any]) -> HarnessWorkerResult: ...


@runtime_checkable
class HarnessGovernancePort(Protocol):
    def evaluate(self, context: dict[str, Any]) -> HarnessQualityVerdict: ...


@runtime_checkable
class HarnessSubagentPort(Protocol):
    def run_subagent(
        self, subagent_id: str, task: dict[str, Any], budget: dict[str, Any]
    ) -> HarnessWorkerResult: ...


@runtime_checkable
class HarnessContextPort(Protocol):
    def assemble(self, context_request: dict[str, Any]) -> ContextEnvelope: ...


@runtime_checkable
class HarnessRAGPort(Protocol):
    def build_context_pack(self, spec: RAGSessionSpec) -> RAGContextPack: ...


@runtime_checkable
class HarnessRetrievalPort(Protocol):
    def retrieve(self, request: RetrievalRequest) -> EvidencePackCollection: ...


@runtime_checkable
class HarnessTracePort(Protocol):
    def write_trace(self, trace: HarnessTrace) -> None: ...


@runtime_checkable
class HarnessSkillEvolutionPort(Protocol):
    def collect_experience(self, request: dict[str, Any]) -> SkillExperience: ...

    def propose_candidate(self, request: dict[str, Any]) -> SkillCandidate: ...

    def evaluate_candidate(
        self, candidate: SkillCandidate
    ) -> SkillEvaluationResult: ...

    def decide_promotion(
        self, evaluation: SkillEvaluationResult
    ) -> SkillPromotionDecision: ...

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease: ...

    def rollback_release(self, release: SkillRelease) -> SkillRollbackPlan: ...


__all__ = [
    "HarnessArtifactPort",
    "HarnessContextPort",
    "HarnessEventPort",
    "HarnessGovernancePort",
    "HarnessGraphResultCommitterPort",
    "HarnessLLMPort",
    "HarnessMemoryPort",
    "HarnessRAGPort",
    "HarnessRetrievalPort",
    "HarnessSkillEvolutionPort",
    "HarnessSkillPort",
    "HarnessSubagentPort",
    "HarnessToolPort",
    "HarnessTracePort",
    "HarnessTransitionPort",
    "HarnessWorkerPort",
]
