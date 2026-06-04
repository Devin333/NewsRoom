from __future__ import annotations

from dataclasses import dataclass

from framework.harness.rag.models import RAGContextPack


@dataclass(frozen=True)
class RAGEvidenceGateResult:
    passed: bool
    missing_evidence_ids: tuple[str, ...] = ()
    missing_source_refs: tuple[str, ...] = ()
    missing_lineage: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "missing_evidence_ids": list(self.missing_evidence_ids),
            "missing_source_refs": list(self.missing_source_refs),
            "missing_lineage": list(self.missing_lineage),
        }


def validate_rag_evidence_refs(pack: RAGContextPack) -> RAGEvidenceGateResult:
    missing_source_refs = tuple(item.evidence_id for item in pack.evidence if not item.source_refs)
    missing_lineage = tuple(item.evidence_id for item in pack.evidence if not item.lineage)
    missing_ids = tuple(item.title for item in pack.evidence if not item.evidence_id)
    return RAGEvidenceGateResult(
        passed=not missing_source_refs and not missing_lineage and not missing_ids,
        missing_evidence_ids=missing_ids,
        missing_source_refs=missing_source_refs,
        missing_lineage=missing_lineage,
    )


__all__ = ["RAGEvidenceGateResult", "validate_rag_evidence_refs"]
