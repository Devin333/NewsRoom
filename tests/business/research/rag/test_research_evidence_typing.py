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
        "figure": "figure",
        "formula": "method",
        "abstract": "claim_support",
    }


def test_research_resolver_prefers_structural_chunk_type_over_section_role() -> None:
    resolver = build_research_evidence_type_resolver()

    assert resolver.resolve({"section_role": ["method"], "chunk_type": "figure"}) == "figure"


def test_research_resolver_falls_back_to_chunk_type_when_role_missing() -> None:
    resolver = build_research_evidence_type_resolver()

    assert resolver.resolve({"chunk_type": "table"}) == "experiment"


def test_research_resolver_uses_section_role_for_plain_paragraphs() -> None:
    resolver = build_research_evidence_type_resolver()

    assert resolver.resolve({"section_role": ["method"], "chunk_type": "paragraph"}) == "method"
