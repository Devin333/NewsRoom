from __future__ import annotations

from framework.harness.rag.evidence_typing import MetadataKeyEvidenceTypeResolver

RESEARCH_EVIDENCE_TYPE_MAPPING: dict[str, dict[str, str]] = {
    "chunk_type": {
        "table": "experiment",
        "figure": "figure",
        "formula": "method",
        "abstract": "claim_support",
    },
    "section_role": {
        "method": "method",
        "experiment": "experiment",
        "analysis": "experiment",
        "conclusion": "limitation",
        "background": "claim_support",
        "related_work": "claim_support",
    },
}


def build_research_evidence_type_resolver() -> MetadataKeyEvidenceTypeResolver:
    return MetadataKeyEvidenceTypeResolver(RESEARCH_EVIDENCE_TYPE_MAPPING)


__all__ = [
    "RESEARCH_EVIDENCE_TYPE_MAPPING",
    "build_research_evidence_type_resolver",
]
