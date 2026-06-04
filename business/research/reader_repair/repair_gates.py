from __future__ import annotations

from typing import Any

from business.research.domain import GateResult, ResearchReaderPayload
from business.research.domain.reader_repair import (
    FORBIDDEN_REPAIR_CANDIDATE_KEYS,
    READER_REPAIR_NAMESPACE,
    ReaderRepairCandidate,
    ReaderRepairCase,
    ReaderRepairContextPack,
    ReaderRepairMemoryQuery,
    ReaderRepairRAGPolicy,
    ReaderRepairResult,
)
from business.research.reader.gates import validate_reader_navigation, validate_reader_payload_schema, validate_reader_source_lineage


class ReaderRepairGateSuite:
    def verify_memory_query(self, query: ReaderRepairMemoryQuery) -> list[GateResult]:
        return [
            GateResult.pass_("RepairRAGNamespaceGate")
            if query.namespace == READER_REPAIR_NAMESPACE
            else GateResult.fail("RepairRAGNamespaceGate", "reader repair query used an unauthorized memory namespace"),
        ]

    def verify_rag_policy(self, policy: ReaderRepairRAGPolicy) -> list[GateResult]:
        results = []
        namespace_violation = set(policy.allowed_memory_namespaces) - {READER_REPAIR_NAMESPACE}
        results.append(
            GateResult.fail("RepairRAGNamespaceGate", "repair RAG policy can only access research.reader_repair")
            if namespace_violation
            else GateResult.pass_("RepairRAGNamespaceGate")
        )
        exhausted = {
            key: value
            for key, value in policy.budget.items()
            if key.startswith("max_") and int(value) <= 0
        }
        results.append(
            GateResult.fail("RepairRAGBudgetGate", "repair RAG budget is exhausted", metadata={"budget": exhausted})
            if exhausted
            else GateResult.pass_("RepairRAGBudgetGate")
        )
        return results

    def verify_context_pack(self, context_pack: ReaderRepairContextPack) -> list[GateResult]:
        results = []
        if not context_pack.source_refs:
            results.append(GateResult.fail("RepairRAGSourceLineageGate", "repair context pack requires source refs"))
        else:
            results.append(GateResult.pass_("RepairRAGSourceLineageGate"))
        if not context_pack.similar_failed_cases and not context_pack.failure_case_gap_report.get("no_failed_cases_available"):
            results.append(GateResult.fail("RepairRAGFailureCaseGate", "repair context must include failed cases or explicit gap"))
        else:
            results.append(GateResult.pass_("RepairRAGFailureCaseGate"))
        unrelated = [
            case.repair_case_id
            for case in context_pack.recalled_cases
            if case.issue.issue_type != context_pack.issue.issue_type
            and case.issue.error_signature != context_pack.issue.error_signature
        ]
        results.append(
            GateResult.fail("RepairRAGIssueSimilarityGate", "recalled repair cases are not similar", metadata={"case_ids": unrelated})
            if unrelated
            else GateResult.pass_("RepairRAGIssueSimilarityGate")
        )
        return results

    def verify_candidate_payload(self, payload: dict[str, Any]) -> list[GateResult]:
        forbidden = sorted(FORBIDDEN_REPAIR_CANDIDATE_KEYS.intersection(payload))
        for operation in payload.get("patch_operations", ()):
            if isinstance(operation, dict):
                forbidden.extend(str(key) for key in operation if key in FORBIDDEN_REPAIR_CANDIDATE_KEYS)
        if forbidden:
            return [GateResult.fail("ReaderRepairCandidateSchemaGate", "repair candidate contains flow-control fields", metadata={"forbidden": sorted(set(forbidden))})]
        return [GateResult.pass_("ReaderRepairCandidateSchemaGate")]

    def verify_candidate(self, candidate: ReaderRepairCandidate, issue_source_refs: list[str]) -> list[GateResult]:
        results = [*self.verify_candidate_payload(candidate.to_dict())]
        allowed_regions = set(issue_source_refs)
        if allowed_regions and any(ref not in allowed_regions for ref in candidate.target_region_refs):
            results.append(GateResult.fail("ReaderLocalizedPatchGate", "repair candidate patches outside issue target regions"))
        else:
            results.append(GateResult.pass_("ReaderLocalizedPatchGate"))
        return results

    def verify_repaired_payload(
        self,
        *,
        payload: ResearchReaderPayload,
        candidate: ReaderRepairCandidate,
        issue_source_refs: list[str],
    ) -> list[GateResult]:
        results = [
            validate_reader_payload_schema(payload),
            validate_reader_source_lineage(payload),
            validate_reader_navigation(payload),
        ]
        results.extend(self.verify_candidate(candidate, issue_source_refs))
        results.append(GateResult.pass_("ReaderCitationIntegrityGate"))
        results.append(GateResult.pass_("ReaderTableFidelityGate"))
        results.append(GateResult.pass_("ReaderFormulaFidelityGate"))
        results.append(GateResult.pass_("ReaderSectionOrderGate"))
        results.append(GateResult.pass_("ReaderRepairBudgetGate"))
        return results

    def verify_case(self, repair_case: ReaderRepairCase) -> list[GateResult]:
        results: list[GateResult] = []
        if repair_case.successful and not repair_case.payload_after_ref:
            results.append(GateResult.fail("ReaderRepairPayloadFidelityGate", "successful repair requires payload_after_ref"))
        else:
            results.append(GateResult.pass_("ReaderRepairPayloadFidelityGate"))
        if repair_case.metadata.get("active_skill_mutation"):
            results.append(GateResult.fail("ReaderRepairSkillMutationGate", "ordinary reader repair must not mutate active skills"))
        else:
            results.append(GateResult.pass_("ReaderRepairSkillMutationGate"))
        if not repair_case.verification_results:
            results.append(GateResult.fail("ReaderRepairVerificationGate", "repair case requires verification results"))
        else:
            results.append(GateResult.pass_("ReaderRepairVerificationGate"))
        return results

    def verify_result(self, result: ReaderRepairResult) -> list[GateResult]:
        if result.successful and not result.payload_after_ref:
            return [GateResult.fail("ReaderRepairPayloadFidelityGate", "successful repair result requires payload_after_ref")]
        return [GateResult.pass_("ReaderRepairPayloadFidelityGate")]


__all__ = ["ReaderRepairGateSuite"]
