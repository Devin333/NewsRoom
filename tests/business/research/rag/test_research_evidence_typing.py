from __future__ import annotations

from business.research.rag.evidence_typing import (
    RESEARCH_EVIDENCE_TYPE_MAPPING,
    build_research_evidence_type_resolver,
)


def test_research_mapping_covers_section_roles() -> None:
    assert RESEARCH_EVIDENCE_TYPE_MAPPING["section_role"] == {
        "method": "method",
        "experiment": "experiment",
        "analysis": "experiment",
        "conclusion": "limitation",
        "background": "claim_support",
        "related_work": "claim_support",
    }


def test_research_mapping_covers_structural_chunk_types() -> None:
    assert RESEARCH_EVIDENCE_TYPE_MAPPING["chunk_type"] == {
        "table": "experiment",
        "figure": "experiment",
        "formula": "method",
        "abstract": "claim_support",
    }


def test_research_resolver_prefers_section_role_over_chunk_type() -> None:
    resolver = build_research_evidence_type_resolver()

    assert resolver.resolve({"section_role": ["method"], "chunk_type": "table"}) == "method"


def test_research_resolver_falls_back_to_chunk_type_when_role_missing() -> None:
    resolver = build_research_evidence_type_resolver()

    assert resolver.resolve({"chunk_type": "table"}) == "experiment"
