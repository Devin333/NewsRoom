from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.research.domain import ResearchReaderPayload, stable_research_id
from business.research.domain.reader_repair import (
    ReaderIssue,
    ReaderRepairAttempt,
    ReaderRepairCandidate,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairRAGPolicy,
    ReaderRepairResult,
)
from business.research.reader_repair.consolidation import ReaderRepairConsolidator
from business.research.reader_repair.issue_detector import ReaderRepairIssueDetector
from business.research.reader_repair.repair_context import ReaderRepairContextBuilder
from business.research.reader_repair.repair_gates import ReaderRepairGateSuite
from business.research.reader_repair.repair_memory import InMemoryReaderRepairMemory, ReaderRepairMemoryService
from business.research.reader_repair.workflow import build_reader_repair_subagent_specs


@dataclass(frozen=True)
class ReaderRepairRunResult:
    issue: ReaderIssue
    context_pack: ReaderRepairContextPack
    candidate: ReaderRepairCandidate
    attempt: ReaderRepairAttempt
    repair_result: ReaderRepairResult
    repair_case: ReaderRepairCase
    memory_ref: str
    context_snapshot_ref: str
    skill_candidate_seed_ref: str | None
    skill_promotion_triggered: bool
    gate_results: list[dict[str, Any]]

    @property
    def successful(self) -> bool:
        return self.repair_result.successful

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue.to_dict(),
            "context_pack": self.context_pack.to_dict(),
            "candidate": self.candidate.to_dict(),
            "attempt": self.attempt.to_dict(),
            "repair_result": self.repair_result.to_dict(),
            "repair_case": self.repair_case.to_dict(),
            "memory_ref": self.memory_ref,
            "context_snapshot_ref": self.context_snapshot_ref,
            "skill_candidate_seed_ref": self.skill_candidate_seed_ref,
            "skill_promotion_triggered": self.skill_promotion_triggered,
            "gate_results": list(self.gate_results),
        }


class ReaderRepairService:
    def __init__(
        self,
        *,
        memory: InMemoryReaderRepairMemory | None = None,
        issue_detector: ReaderRepairIssueDetector | None = None,
        context_builder: ReaderRepairContextBuilder | None = None,
        gates: ReaderRepairGateSuite | None = None,
        consolidator: ReaderRepairConsolidator | None = None,
    ) -> None:
        self.memory_service = ReaderRepairMemoryService(memory or InMemoryReaderRepairMemory())
        self.issue_detector = issue_detector or ReaderRepairIssueDetector()
        self.context_builder = context_builder or ReaderRepairContextBuilder()
        self.gates = gates or ReaderRepairGateSuite()
        self.consolidator = consolidator or ReaderRepairConsolidator()

    def repair_reader_payload(
        self,
        *,
        payload: ResearchReaderPayload,
        run_id: str,
        candidate_payload: dict[str, Any] | None = None,
        repaired_payload_ref: str | None = None,
        source_format: str | None = "pdf",
    ) -> ReaderRepairRunResult:
        issues = self.issue_detector.detect(payload, run_id=run_id, source_format=source_format)
        if not issues:
            raise ValueError("reader repair requires a detected reader issue")
        issue = issues[0]
        query = self.memory_service.build_query(issue, source_format=source_format)
        policy = ReaderRepairRAGPolicy(policy_id=stable_research_id("repair_rag_policy", issue.error_signature))
        recalled = self.memory_service.recall(query)
        context_pack = self.context_builder.build_pack(
            issue=issue,
            query=query,
            successful_cases=list(recalled["similar_successful_cases"]),
            failed_cases=list(recalled["similar_failed_cases"]),
            strategies=list(recalled["promoted_strategies"]),
            policy=policy,
        )
        context_result = self.context_builder.assemble_for_subagent(
            context_pack=context_pack,
            run_id=run_id,
            step_id="propose_repair_candidate",
            subagent_id="reader_repair_proposer",
            role="proposer",
        )
        candidate_input = dict(candidate_payload or {})
        candidate_metadata = {
            "raw_candidate_forbidden_keys": sorted(set(candidate_input).intersection({"next_step", "quality_passed", "write_memory", "publish", "publish_artifact", "promote_skill"}))
        }
        sanitized_patch_operations = []
        forbidden_operation_keys: list[str] = []
        for operation in list(candidate_input.get("patch_operations", [{"op": "replace_region", "path": issue.payload_ref or issue.issue_id}])):
            if not isinstance(operation, dict):
                continue
            forbidden_operation_keys.extend(
                str(key)
                for key in operation
                if key in {"next_step", "quality_passed", "write_memory", "publish", "publish_artifact", "promote_skill"}
            )
            sanitized_patch_operations.append(
                {key: value for key, value in operation.items() if key not in {"next_step", "quality_passed", "write_memory", "publish", "publish_artifact", "promote_skill"}}
            )
        if forbidden_operation_keys:
            candidate_metadata["raw_operation_forbidden_keys"] = sorted(set(forbidden_operation_keys))
        candidate = ReaderRepairCandidate(
            candidate_id=stable_research_id("repair_candidate", issue.issue_id),
            repair_summary=str(candidate_input.get("repair_summary", "Repair reader payload issue with a localized patch.")),
            target_region_refs=list(candidate_input.get("target_region_refs", issue.source_refs or [issue.payload_ref or issue.issue_id])),
            patch_operations=sanitized_patch_operations or [{"op": "replace_region", "path": issue.payload_ref or issue.issue_id}],
            expected_effect=str(candidate_input.get("expected_effect", "Reader payload passes schema and lineage gates.")),
            risks=list(candidate_input.get("risks", ["patch may not generalize"])),
            confidence=float(candidate_input.get("confidence", 0.82)),
            metadata=candidate_metadata,
        )
        proposer_spec, verifier_spec = build_reader_repair_subagent_specs()
        attempt = ReaderRepairAttempt(
            attempt_id=stable_research_id("repair_attempt", issue.issue_id, candidate.candidate_id),
            issue_id=issue.issue_id,
            proposer_subagent_id=proposer_spec.subagent_id,
            verifier_subagent_id=verifier_spec.subagent_id,
            candidate=candidate,
            context_snapshot_ref=context_result.context_envelope.snapshot_ref or context_result.context_envelope.envelope_id,
            handoff_ref=stable_research_id("repair_handoff", proposer_spec.subagent_id, verifier_spec.subagent_id, candidate.candidate_id),
        )
        verification_results = [
            *self.gates.verify_memory_query(query),
            *self.gates.verify_rag_policy(policy),
            *self.gates.verify_context_pack(context_pack),
            *self.gates.verify_candidate_payload(candidate_input),
            *self.gates.verify_candidate(candidate, issue.source_refs),
        ]
        successful = all(result.passed for result in verification_results)
        repair_result = ReaderRepairResult(
            result_id=stable_research_id("repair_result", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            successful=successful,
            verification_results=[result.to_dict() for result in verification_results],
            payload_before_ref=issue.payload_ref or payload.payload_id,
            payload_after_ref=repaired_payload_ref or (f"{payload.payload_id}:repaired" if successful else None),
            source_refs=issue.source_refs,
            failure_reason=None if successful else "reader repair verification failed",
            metadata={"skill_promotion_triggered": False},
        )
        repair_case = ReaderRepairCase(
            repair_case_id=stable_research_id("repair_case", issue.issue_id, attempt.attempt_id),
            issue=issue,
            memory_kind="episodic",
            repair_strategy=candidate.repair_summary,
            repair_attempt_refs=[attempt.attempt_id],
            successful=repair_result.successful,
            verification_results=repair_result.verification_results,
            payload_before_ref=repair_result.payload_before_ref,
            payload_after_ref=repair_result.payload_after_ref,
            source_refs=repair_result.source_refs,
            constraints=context_pack.repair_constraints,
            failure_reason=repair_result.failure_reason,
            tags=[issue.issue_type, issue.error_signature],
            metadata={"active_skill_mutation": False, "context_snapshot_ref": attempt.context_snapshot_ref},
        )
        case_gate_results = self.gates.verify_case(repair_case)
        memory_ref = self.memory_service.commit_case(repair_case)
        strategies = self.consolidator.consolidate(list(self.memory_service.memory.cases.values()))
        seed_ref = None
        for strategy in strategies:
            self.memory_service.memory.write_strategy(strategy)
            seed = self.consolidator.skill_candidate_seed(strategy)
            if seed is not None:
                seed_ref = f"skill-candidate-seed://{seed.seed_id}"
                break
        return ReaderRepairRunResult(
            issue=issue,
            context_pack=context_result.context_pack,
            candidate=candidate,
            attempt=attempt,
            repair_result=repair_result,
            repair_case=repair_case,
            memory_ref=memory_ref,
            context_snapshot_ref=attempt.context_snapshot_ref,
            skill_candidate_seed_ref=seed_ref,
            skill_promotion_triggered=False,
            gate_results=[result.to_dict() for result in [*verification_results, *case_gate_results]],
        )


__all__ = ["ReaderRepairRunResult", "ReaderRepairService"]
