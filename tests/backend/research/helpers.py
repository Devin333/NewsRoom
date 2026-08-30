from __future__ import annotations

from datetime import UTC, datetime

from backend.research.domain import (
    EvidenceRef,
    ResearchDocument,
    ResearchPaper,
    ResearchSection,
    SourceLineage,
    ThreeMinuteRead,
)


FIXED_NOW = datetime(2026, 6, 5, 8, 0, tzinfo=UTC)


def sample_paper() -> ResearchPaper:
    return ResearchPaper(
        paper_id="paper-1",
        title="Harnessed Research Agents",
        authors=["Ada Lovelace", "Grace Hopper"],
        abstract="A paper about controlled research agents.",
        published_at=FIXED_NOW,
        source="arxiv",
        source_url="https://arxiv.org/abs/2606.00001",
        pdf_url="https://arxiv.org/pdf/2606.00001",
        code_url="https://github.com/newsroom/harnessed-research",
        topics=["agents", "research"],
    )


def sample_document() -> ResearchDocument:
    return ResearchDocument(
        paper_id="paper-1",
        source_hash="sha256-paper-1",
        sections=[
            ResearchSection(
                section_id="sec-intro",
                title="Introduction",
                level=1,
                text="Harness owns routing, gates, memory writes, and publication.",
                source_ref="paper://paper-1/sec-intro",
            )
        ],
        lineage=SourceLineage(source_refs=["paper://paper-1"], source_hash="sha256-paper-1"),
    )


def sample_three_minute_read() -> ThreeMinuteRead:
    return ThreeMinuteRead(
        problem="Research agents need deterministic control.",
        core_idea="Separate Harness routing from LLM candidate generation.",
        key_contributions=["Bounded RAG", "Deterministic gates"],
        method_summary="A controlled PLAN EXECUTE VERIFY runtime.",
        experiment_summary="Evaluated with fake workers.",
        limitations=["Single-paper loop first"],
        why_it_matters="It keeps research outputs auditable.",
        read_next=["Reader repair memory"],
        evidence_refs=[
            EvidenceRef(
                evidence_id="evidence-intro",
                source_ref="paper://paper-1/sec-intro",
                section_id="sec-intro",
                confidence=1.0,
            )
        ],
        confidence=0.91,
    )
