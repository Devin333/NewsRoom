from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.harness import ContextAssembler, ContextBudget, ContextEnvelope
from framework.harness.context.models import ContextGraphIdentity

from backend.research.domain import SourceLineage, stable_research_id
from backend.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderIssue,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairMemoryQuery,
    ReaderRepairRAGPolicy,
    ReaderRepairStrategy,
)


@dataclass(frozen=True)
class ReaderRepairContextBuildResult:
    context_pack: ReaderRepairContextPack
    context_envelope: ContextEnvelope
    compression_records: tuple[dict[str, Any], ...]


class ReaderRepairContextBuilder:
    def __init__(self, context_assembler: ContextAssembler | None = None) -> None:
        self.context_assembler = context_assembler or ContextAssembler()

    def build_pack(
        self,
        *,
        issue: ReaderIssue,
        query: ReaderRepairMemoryQuery,
        successful_cases: list[ReaderRepairCase],
        failed_cases: list[ReaderRepairCase],
        strategies: list[ReaderRepairStrategy],
        policy: ReaderRepairRAGPolicy | None = None,
        rag_session_id: str | None = None,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> ReaderRepairContextPack:
        policy = policy or ReaderRepairRAGPolicy(policy_id=stable_research_id("repair_rag_policy", issue.error_signature))
        accepted_refs = [
            f"memory://{query.namespace}/case/{case.repair_case_id}"
            for case in [*successful_cases, *failed_cases]
        ] + [f"memory://{query.namespace}/strategy/{strategy.strategy_id}" for strategy in strategies]
        return ReaderRepairContextPack(
            context_id=stable_research_id("reader_repair_context", issue.paper_id, issue.error_signature),
            issue=issue,
            similar_successful_cases=successful_cases,
            similar_failed_cases=failed_cases,
            promoted_strategies=strategies,
            repair_constraints=[
                "preserve source lineage",
                "only patch issue target regions",
                "keep failed-case boundaries visible",
            ],
            source_refs=issue.source_refs,
            source_lineage=SourceLineage(source_refs=issue.source_refs or ["source://reader-repair/missing-lineage"]),
            rag_session_id=rag_session_id or stable_research_id("repair_rag_session", issue.paper_id, issue.error_signature),
            accepted_memory_refs=accepted_refs,
            failure_case_gap_report={} if failed_cases else {"no_failed_cases_available": True},
            budget_snapshot=budget_snapshot or policy.budget,
            metadata={
                "namespace": READER_REPAIR_NAMESPACE,
                "query_id": query.query_id,
                "allowed_memory_namespaces": policy.allowed_memory_namespaces,
            },
        )

    def assemble_for_subagent(
        self,
        *,
        context_pack: ReaderRepairContextPack,
        graph_identity: ContextGraphIdentity,
        subagent_id: str,
        role: str,
        max_input_tokens: int = 4096,
        evidence_memory_tokens: int = 160,
    ) -> ReaderRepairContextBuildResult:
        envelope = self.context_assembler.assemble(
            {
                "run_id": graph_identity.run_id,
                "step_id": graph_identity.stage_id,
                "graph_identity": graph_identity,
                "phase": "execute",
                "worker_id": subagent_id,
                "worker_type": "subagent",
                "graph_ref": graph_identity.graph_ref,
                "worker_contract_ref": f"schema://research.reader_repair/{role}",
                "run_state_ref": f"run-state://{graph_identity.run_id}",
                "evidence_memory_ref": context_pack.context_id,
                "current_task_ref": f"task://{graph_identity.stage_id}",
                "current_instruction": "Generate or verify a reader repair candidate without deciding routing, memory writes, or skill promotion.",
                "source_refs": context_pack.source_refs,
                "artifact_refs": tuple(ref for case in context_pack.recalled_cases for ref in (case.payload_before_ref, case.payload_after_ref) if ref),
                "evidence_refs": tuple(context_pack.source_refs),
                "allowed_tools": ("retrieval.read_source",),
                "allowed_memory_namespaces": (READER_REPAIR_NAMESPACE,),
                "budget": ContextBudget(
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=1024,
                    max_context_segments=6,
                    max_evidence_items=8,
                    max_memory_items=8,
                    max_artifact_refs=24,
                    reserved_output_tokens=512,
                    compression_threshold=0.8,
                ),
                "evidence_memory_tokens": evidence_memory_tokens,
                "metadata": {
                    "issue_signature": context_pack.issue.error_signature,
                    "failure_case_gap_report": context_pack.failure_case_gap_report,
                    "stable_prefix_excludes": ["proposer_private_notes", "raw_history", "hidden_prompt"],
                },
            }
        )
        compression_records = self.context_assembler.compression_record_projections(
            envelope_id=envelope.envelope_id,
        )
        return ReaderRepairContextBuildResult(
            context_pack=context_pack,
            context_envelope=envelope,
            compression_records=compression_records,
        )


__all__ = ["ReaderRepairContextBuildResult", "ReaderRepairContextBuilder"]
